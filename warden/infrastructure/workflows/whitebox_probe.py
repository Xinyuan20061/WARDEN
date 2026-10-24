"""真实 Hugging Face 模型的 Activation Corpus 与 Probe Suite 工作流。"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from warden.core.domain.models import CaptureTarget, to_primitive
from warden.infrastructure.adapters.huggingface import (
    HuggingFaceModelConfig,
    build_huggingface_runtime,
)
from warden.infrastructure.adapters.stegopot_features import (
    StegoPotActivationFeatureExtractor,
)
from warden.infrastructure.data import (
    ActivationCorpusBuilder,
    load_activation_corpus,
    load_interaction_dataset,
    save_activation_corpus,
)
from warden.infrastructure.methods.probe import ProbeSuiteTrainer

RunPhase = Literal["collect", "train", "all"]


@dataclass(frozen=True, slots=True)
class WhiteBoxProbeExperimentConfig:
    """一次可复现白盒 Probe 实验的完整静态配置。

    属性：
        schema_version: 配置契约版本。
        experiment_id: 本次实验的稳定标识。
        model_id: 写入审计工件的逻辑模型标识。
        model: Hugging Face 模型加载参数。
        dataset_path: 家族隔离三分数据集的 JSONL 路径。
        output_directory: Activation Corpus 与 Probe Suite 输出目录。
        agent_ids: 参与联合读出的稳定 Agent 标识及顺序。
        capture_targets: 需要采集的层级、组件和 token 位置。
        probe_c: Logistic Regression 的 L2 正则倒数。
        probe_max_iter: 单个候选 Probe 的最大优化迭代数。
        random_seed: Probe 训练使用的随机种子。
    """

    schema_version: str
    experiment_id: str
    model_id: str
    model: HuggingFaceModelConfig
    dataset_path: Path
    output_directory: Path
    agent_ids: Sequence[str]
    capture_targets: Sequence[CaptureTarget]
    probe_c: float = 1.0
    probe_max_iter: int = 2000
    random_seed: int = 0

    def __post_init__(self) -> None:
        """校验配置版本、标识、主体和采集位置。"""

        if self.schema_version != "warden.whitebox-probe-experiment/1":
            raise ValueError("whitebox probe 配置 schema_version 不受支持")
        for name in ("experiment_id", "model_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 必须是非空字符串")
        agents = tuple(str(item).strip() for item in self.agent_ids)
        if not agents or any(not item for item in agents) or len(set(agents)) != len(agents):
            raise ValueError("agent_ids 必须非空且不能重复")
        targets = tuple(self.capture_targets)
        if not targets or len({item.target_id for item in targets}) != len(targets):
            raise ValueError("capture_targets 必须非空且 target_id 不能重复")
        for target in targets:
            unknown = set(target.agent_ids) - set(agents)
            if unknown:
                raise ValueError(
                    f"CaptureTarget {target.target_id} 引用了未声明 Agent：{sorted(unknown)}"
                )
            if target.retain_gradient:
                raise ValueError("Probe Corpus 采集不保留梯度；EAP 应使用独立因果阶段")
            if target.token_policy == "all":
                raise ValueError(
                    "Probe Corpus 不支持 all token_policy；请使用 last_token 或 mean_tokens"
                )
        if self.probe_c <= 0 or self.probe_max_iter < 1:
            raise ValueError("probe_c 和 probe_max_iter 必须为正数")
        object.__setattr__(self, "agent_ids", agents)
        object.__setattr__(self, "capture_targets", targets)
        object.__setattr__(self, "dataset_path", Path(self.dataset_path).resolve())
        object.__setattr__(self, "output_directory", Path(self.output_directory).resolve())


def load_whitebox_probe_config(path: Path) -> WhiteBoxProbeExperimentConfig:
    """严格读取 JSON 配置并解析相对路径。

    参数：
        path: 实验 JSON 配置文件。

    返回：
        完成字段和路径检查的不可变配置。
    """

    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"找不到白盒实验配置：{source}")
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("白盒实验配置根节点必须是对象")
    allowed = {
        "schema_version",
        "experiment_id",
        "model_id",
        "model",
        "dataset_path",
        "output_directory",
        "agent_ids",
        "capture_targets",
        "probe",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("白盒实验配置包含未知字段：" + ", ".join(unknown))
    model_value = value.get("model")
    if not isinstance(model_value, dict):
        raise ValueError("model 必须是对象")
    probe_value = value.get("probe", {})
    if not isinstance(probe_value, dict):
        raise ValueError("probe 必须是对象")
    unknown_probe = sorted(set(probe_value) - {"c", "max_iter", "random_seed"})
    if unknown_probe:
        raise ValueError("probe 包含未知字段：" + ", ".join(unknown_probe))
    base = source.parent
    model = HuggingFaceModelConfig(**model_value).resolve_paths(base)
    targets_value = value.get("capture_targets")
    if not isinstance(targets_value, list):
        raise ValueError("capture_targets 必须是数组")
    targets = tuple(CaptureTarget(**item) for item in targets_value)
    return WhiteBoxProbeExperimentConfig(
        schema_version=value["schema_version"],
        experiment_id=value["experiment_id"],
        model_id=value["model_id"],
        model=model,
        dataset_path=_resolve_path(base, value["dataset_path"]),
        output_directory=_resolve_path(base, value["output_directory"]),
        agent_ids=tuple(value["agent_ids"]),
        capture_targets=targets,
        probe_c=float(probe_value.get("c", 1.0)),
        probe_max_iter=int(probe_value.get("max_iter", 2000)),
        random_seed=int(probe_value.get("random_seed", 0)),
    )


def preflight_whitebox_probe_experiment(
    config: WhiteBoxProbeExperimentConfig,
) -> Mapping[str, Any]:
    """不加载模型地检查依赖、路径、数据和复现风险。

    参数：
        config: 已完成静态字段校验的实验配置。

    返回：
        可序列化的检查列表、阻塞项数量、警告数量和就绪状态。

    说明：
        该函数不会加载权重或执行前向传播，因此不能代替真实运行检查。
    """

    checks: list[dict[str, Any]] = []
    for package in ("numpy", "sklearn", "torch", "transformers", "stegopot"):
        available = importlib.util.find_spec(package) is not None
        checks.append(
            {
                "check_id": f"dependency.{package}",
                "status": "pass" if available else "blocked",
                "message": "已安装" if available else f"缺少 Python 包：{package}",
            }
        )
    model_path = Path(config.model.model_path)
    if config.model.local_files_only:
        required_files = (
            model_path.is_dir()
            and (model_path / "config.json").is_file()
            and (model_path / "tokenizer_config.json").is_file()
        )
        has_weights = model_path.is_dir() and (
            any(model_path.glob("*.safetensors"))
            or any(model_path.glob("*.bin"))
        )
        available = bool(required_files and has_weights)
        checks.append(
            {
                "check_id": "model.local_snapshot",
                "status": "pass" if available else "blocked",
                "message": (
                    f"本地模型快照：{model_path}"
                    if available
                    else f"本地模型快照不完整或不存在：{model_path}"
                ),
            }
        )
    else:
        checks.append(
            {
                "check_id": "model.network_loading",
                "status": "warning",
                "message": "配置允许运行时联网下载；正式实验建议先固定本地快照",
            }
        )
    if config.model.revision is None:
        checks.append(
            {
                "check_id": "model.revision",
                "status": "warning",
                "message": "模型 revision 未固定；发布结果前应记录提交哈希",
            }
        )
    if config.model.quantization != "none":
        checks.append(
            {
                "check_id": "model.quantization",
                "status": "warning",
                "message": "量化会改变内部表征；关键结论需用全精度或另一精度复核",
            }
        )
    if importlib.util.find_spec("torch") is not None and config.model.device.startswith("cuda"):
        import torch

        cuda_available = bool(torch.cuda.is_available())
        checks.append(
            {
                "check_id": "device.cuda",
                "status": "pass" if cuda_available else "blocked",
                "message": (
                    f"CUDA 可用：{torch.cuda.get_device_name(0)}"
                    if cuda_available
                    else "配置要求 CUDA，但 PyTorch 未检测到可用 GPU"
                ),
            }
        )
        if cuda_available and config.model.dtype == "bfloat16":
            supports_bf16 = getattr(torch.cuda, "is_bf16_supported", lambda: False)()
            checks.append(
                {
                    "check_id": "device.bfloat16",
                    "status": "pass" if supports_bf16 else "blocked",
                    "message": (
                        "当前 GPU 支持 bfloat16"
                        if supports_bf16
                        else "当前 GPU 不支持 bfloat16，请把 dtype 改为 float16"
                    ),
                }
            )
    try:
        dataset = load_interaction_dataset(config.dataset_path)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        checks.append(
            {
                "check_id": "dataset.contract",
                "status": "blocked",
                "message": str(exc),
            }
        )
    else:
        same_agents = tuple(dataset.agent_ids) == tuple(sorted(config.agent_ids))
        checks.append(
            {
                "check_id": "dataset.contract",
                "status": "pass" if same_agents else "blocked",
                "message": (
                    f"数据集通过三分与家族隔离检查，样本数={len(dataset.samples)}"
                    if same_agents
                    else "数据集 Agent 集合与配置不一致"
                ),
                "dataset_fingerprint": dataset.fingerprint,
            }
        )
    warnings = sum(item["status"] == "warning" for item in checks)
    blocked = sum(item["status"] == "blocked" for item in checks)
    return {
        "schema_version": "warden.whitebox-preflight/1",
        "experiment_id": config.experiment_id,
        "ready": blocked == 0,
        "blocked_checks": blocked,
        "warnings": warnings,
        "checks": checks,
    }


def run_whitebox_probe_experiment(
    config: WhiteBoxProbeExperimentConfig,
    *,
    phase: RunPhase = "all",
    progress: Callable[[str], None] | None = None,
) -> Mapping[str, Any]:
    """分阶段采集真实 Activation 并训练 Probe Suite。

    参数：
        config: 已加载的白盒实验配置。
        phase: `collect` 只执行 GPU 前向，`train` 只消费已有 Corpus，
            `all` 顺序执行两者。
        progress: 可选进度回调，接收不含样本内容和张量的状态文本。

    返回：
        包含 Corpus 和 Probe 报告路径的可序列化摘要。
    """

    if phase not in {"collect", "train", "all"}:
        raise ValueError("phase 只支持 collect、train 或 all")
    notify = progress or (lambda _message: None)
    root = config.output_directory
    root.mkdir(parents=True, exist_ok=True)
    corpus_root = root / "activation_corpus"
    probe_root = root / "probe_suite"
    if phase in {"collect", "all"}:
        preflight = preflight_whitebox_probe_experiment(config)
        if not preflight["ready"]:
            reasons = [
                item["message"]
                for item in preflight["checks"]
                if item["status"] == "blocked"
            ]
            raise RuntimeError("白盒实验预检未通过：" + "; ".join(reasons))
        if corpus_root.exists():
            raise FileExistsError(f"Activation Corpus 已存在：{corpus_root}")
        dataset = load_interaction_dataset(config.dataset_path)
        notify("正在加载本地 Hugging Face 模型")
        runtime = build_huggingface_runtime(config.model)
        extractor = StegoPotActivationFeatureExtractor(
            {agent_id: runtime for agent_id in config.agent_ids},
            model_id=config.model_id,
            own_runtimes=True,
        )
        try:
            notify(f"开始采集 {len(dataset.samples)} 个样本的选择性 Activation")
            corpus = ActivationCorpusBuilder(extractor).build(
                dataset,
                config.capture_targets,
            )
            save_activation_corpus(corpus, corpus_root)
        finally:
            extractor.close()
        notify("Activation Corpus 已保存，模型资源已释放")
    if phase in {"train", "all"}:
        if probe_root.exists():
            raise FileExistsError(f"Probe Suite 已存在：{probe_root}")
        corpus = load_activation_corpus(corpus_root)
        notify("开始在声明的 train/validation/test 切分上训练 Probe Suite")
        report = ProbeSuiteTrainer(
            c=config.probe_c,
            max_iter=config.probe_max_iter,
            random_seed=config.random_seed,
        ).fit(corpus, probe_root)
        notify("Probe Suite 训练和独立测试完成")
    else:
        report = None
    summary = {
        "schema_version": "warden.whitebox-probe-run/1",
        "experiment_id": config.experiment_id,
        "phase": phase,
        "model_id": config.model_id,
        "dataset_path": str(config.dataset_path),
        "output_directory": str(root),
        "activation_corpus": str(corpus_root),
        "probe_suite_report": str(probe_root / "report.json") if report else None,
        "capture_targets": [to_primitive(item) for item in config.capture_targets],
    }
    _write_json_atomic(summary, root / f"run-{phase}.json")
    return summary


def _resolve_path(base: Path, value: Any) -> Path:
    """把配置中的相对路径解析为绝对路径。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("路径字段必须是非空字符串")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _write_json_atomic(payload: Mapping[str, Any], destination: Path) -> None:
    """原子写入工作流摘要。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(destination)
