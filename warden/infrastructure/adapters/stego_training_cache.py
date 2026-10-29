"""绑定实际内容的训练缓存；临时构建、原子发布，读取失败时关闭执行。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import mkdtemp


def file_digest(path: Path) -> str:
    """流式读取完整文件；不以大小或修改时间代替内容身份。"""
    result = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def model_content_hashes(model) -> dict:
    """覆盖分片权重、索引、模型配置与独立 tokenizer 的全部资源。"""
    files = {}
    for prefix, root in (
        ("model", Path(model.model_path)),
        ("tokenizer", Path(model.tokenizer_path or model.model_path)),
    ):
        if not root.exists():
            continue
        for item in sorted(root.rglob("*")):
            if item.is_file() and item.suffix in {
                ".safetensors",
                ".bin",
                ".json",
                ".txt",
                ".model",
                ".tiktoken",
                ".jinja",
            }:
                if prefix == "tokenizer" and item.suffix in {".safetensors", ".bin"}:
                    continue
                files[prefix + "/" + item.relative_to(root).as_posix()] = file_digest(item)
    return files


def training_inputs(config_path, config, model, *, code_paths) -> dict:
    """记录所有冻结输入及依赖；任何关键内容漂移会生成新身份。"""
    dependencies = {}
    for name in ("torch", "transformers", "concept-erasure", "numpy", "scikit-learn"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = "not-installed"
    return {
        "schema_version": "warden.training-inputs/2",
        "config_sha256": file_digest(Path(config_path)),
        "dataset_sha256": file_digest(config["dataset_path"]),
        "split_sha256": file_digest(config["split_path"]),
        "model_files_sha256": model_content_hashes(model),
        "model_revision": model.revision,
        "tokenizer_revision": model.revision,
        "code_sha256": {Path(p).name: file_digest(Path(p)) for p in code_paths},
        "layer": config["layer"],
        "component": "resid_post",
        "token": -1,
        "generation_step": 0,
        "seed": config["seed"],
        "label_semantics": "secret_bit",
        "training_set_version": "train-only/2",
        "dependencies": dependencies,
    }


def cache_identity(inputs: dict) -> str:
    """返回规范 JSON 的 SHA256。"""
    return sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_cache(path: Path, inputs: dict) -> dict:
    """同时验证输入指纹、完成标记和每个输出内容；损坏绝不静默重训。"""
    marker = path / "complete.json"
    if not marker.is_file():
        raise ValueError("训练缓存未完成，禁止复用")
    saved = json.loads(marker.read_text(encoding="utf-8"))
    if saved.get("inputs") != inputs or saved.get("identity") != cache_identity(inputs):
        raise ValueError("训练缓存输入指纹不匹配")
    hashes = saved.get("hashes", {})
    actual = {
        p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file() and p != marker
    }
    if not hashes or actual != set(hashes):
        raise ValueError("训练缓存输出清单不完整")
    for name, digest in hashes.items():
        item = (path / name).resolve()
        if not item.is_relative_to(path.resolve()) or file_digest(item) != digest:
            raise ValueError("训练缓存内容哈希不匹配")
    return saved


@contextmanager
def atomic_training_cache(root: Path, inputs: dict):
    """返回 (工作目录, 是否新建)；成功退出才原子发布，失败目录保留供审计。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / cache_identity(inputs)
    if final.exists():
        verify_cache(final, inputs)
        yield final, False
        return
    work = Path(mkdtemp(prefix=".building-", dir=root))
    yield work, True
    # 先验证训练期间输入未漂移由调用方负责；半成品永远没有最终身份路径。
    extra = json.loads((work / "training.json").read_text(encoding="utf-8"))
    hashes = {
        p.relative_to(work).as_posix(): file_digest(p) for p in work.rglob("*") if p.is_file()
    }
    marker = {**extra, "inputs": inputs, "identity": cache_identity(inputs), "hashes": hashes}
    (work / "complete.json").write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
    verify_cache(work, inputs)
    if final.exists():
        verify_cache(final, inputs)
    else:
        work.rename(final)
