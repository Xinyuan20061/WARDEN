"""Hugging Face 白盒模型的配置与 StegoPot 组合入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class HuggingFaceModelConfig:
    """构建 StegoPot HuggingFaceAdapter 所需的显式参数。

    属性：
        model_path: 本地模型目录或 Hugging Face 模型标识。
        tokenizer_path: 可选分词器目录；为空时与模型共用来源。
        revision: 模型仓库提交、标签或分支；正式实验建议固定提交哈希。
        device: StegoPot 模型设备，例如 ``cuda``、``cpu`` 或 ``auto``。
        dtype: 模型权重精度。
        trust_remote_code: 是否允许执行模型仓库提供的自定义代码。
        local_files_only: 是否禁止运行时联网下载模型文件。
        use_safetensors: 是否要求优先使用 safetensors 权重。
        parameter_gradients: 是否为模型参数保留梯度。
        quantization: 量化方式，支持不量化、bitsandbytes 4 位或 8 位。
        bnb_4bit_compute_dtype: 4 位量化的计算精度。
        bnb_4bit_quant_type: 4 位量化编码类型。
        bnb_4bit_use_double_quant: 是否启用嵌套量化。
    """

    model_path: str
    tokenizer_path: str | None = None
    revision: str | None = None
    device: str = "auto"
    dtype: str = "auto"
    trust_remote_code: bool = False
    local_files_only: bool = True
    use_safetensors: bool = True
    parameter_gradients: bool = False
    quantization: str = "none"
    bnb_4bit_compute_dtype: str = "bfloat16"
    bnb_4bit_quant_type: str = "nf4"
    bnb_4bit_use_double_quant: bool = True

    def __post_init__(self) -> None:
        """拒绝空路径、未知精度和未知量化方式。"""

        if not isinstance(self.model_path, str) or not self.model_path.strip():
            raise ValueError("model_path 必须是非空字符串")
        if self.dtype not in {"auto", "float32", "float16", "bfloat16"}:
            raise ValueError("dtype 不受支持")
        if self.quantization not in {"none", "bnb_4bit", "bnb_8bit"}:
            raise ValueError("quantization 不受支持")
        if self.bnb_4bit_compute_dtype not in {"float32", "float16", "bfloat16"}:
            raise ValueError("bnb_4bit_compute_dtype 不受支持")
        if self.bnb_4bit_quant_type not in {"nf4", "fp4"}:
            raise ValueError("bnb_4bit_quant_type 不受支持")

    def resolve_paths(self, base_directory: Path) -> HuggingFaceModelConfig:
        """把相对本地路径解析到配置文件所在目录。

        参数：
            base_directory: 相对路径的基准目录，通常是实验配置文件所在目录。

        返回：
            路径已规范化的新配置；当前对象保持不变。
        """

        base = Path(base_directory).resolve()

        def resolve(value: str | None) -> str | None:
            if value is None:
                return None
            candidate = Path(value)
            if candidate.is_absolute():
                return str(candidate)
            local = base / candidate
            if self.local_files_only or value.startswith((".", "..")) or local.exists():
                return str(local.resolve())
            return value

        return HuggingFaceModelConfig(
            model_path=resolve(self.model_path) or self.model_path,
            tokenizer_path=resolve(self.tokenizer_path),
            revision=self.revision,
            device=self.device,
            dtype=self.dtype,
            trust_remote_code=self.trust_remote_code,
            local_files_only=self.local_files_only,
            use_safetensors=self.use_safetensors,
            parameter_gradients=self.parameter_gradients,
            quantization=self.quantization,
            bnb_4bit_compute_dtype=self.bnb_4bit_compute_dtype,
            bnb_4bit_quant_type=self.bnb_4bit_quant_type,
            bnb_4bit_use_double_quant=self.bnb_4bit_use_double_quant,
        )

    def to_adapter_kwargs(self) -> dict[str, Any]:
        """返回 StegoPot HuggingFaceAdapter 的关键字参数。"""

        return {
            "model_path": self.model_path,
            "tokenizer_path": self.tokenizer_path,
            "revision": self.revision,
            "device": self.device,
            "dtype": self.dtype,
            "trust_remote_code": self.trust_remote_code,
            "local_files_only": self.local_files_only,
            "use_safetensors": self.use_safetensors,
            "parameter_gradients": self.parameter_gradients,
            "quantization": self.quantization,
            "bnb_4bit_compute_dtype": self.bnb_4bit_compute_dtype,
            "bnb_4bit_quant_type": self.bnb_4bit_quant_type,
            "bnb_4bit_use_double_quant": self.bnb_4bit_use_double_quant,
        }


def build_huggingface_runtime(config: HuggingFaceModelConfig) -> Any:
    """惰性构建 StegoPot ModelRuntime，不在基础安装时导入 PyTorch。

    参数：
        config: 已验证的 Hugging Face 模型加载配置。

    返回：
        拥有底层模型适配器生命周期的 StegoPot ``ModelRuntime``。

    异常：
        RuntimeError: 未安装 StegoPot 白盒依赖时抛出。

    资源所有权：
        调用方必须关闭返回的 Runtime，或把所有权交给其他可关闭组件。
    """

    try:
        from stegopot.application.services.runtime.model import ModelRuntime
        from stegopot.infrastructure.model_adapters.huggingface import HuggingFaceAdapter
    except ImportError as exc:
        raise RuntimeError(
            "加载本地白盒模型需要安装 vendor/stegopot[whitebox]"
        ) from exc
    adapter = HuggingFaceAdapter(**config.to_adapter_kwargs())
    return ModelRuntime(adapter, own_adapter=True)
