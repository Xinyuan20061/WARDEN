"""从不含权重的 JSON 清单发现 Probe 与 SAE 资源。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from warden.core.domain.enums import ResourceState
from warden.core.domain.models import ArtifactRef, ResourceManifest


def discover_resource_manifests(*roots: Path) -> tuple[ResourceManifest, ...]:
    """递归读取 manifest.json，并拒绝重复资源标识。"""

    resources: dict[str, ResourceManifest] = {}
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in sorted(root.rglob("manifest.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"资源清单根节点必须是对象：{path}")
            resource = _parse_manifest(value, path)
            if resource.resource_id in resources:
                raise ValueError(f"资源 ID 重复：{resource.resource_id}")
            resources[resource.resource_id] = resource
    return tuple(resources[key] for key in sorted(resources))


def _parse_manifest(value: Mapping[str, Any], path: Path) -> ResourceManifest:
    """把稳定公共字段转换为 ResourceManifest。"""

    artifact_value = value.get("artifact")
    artifact = ArtifactRef(**artifact_value) if isinstance(artifact_value, Mapping) else None
    metadata = dict(value.get("metadata", {}))
    metadata.setdefault("manifest_path", str(path.resolve()))
    return ResourceManifest(
        resource_id=str(value["resource_id"]),
        kind=str(value["kind"]),
        version=str(value["version"]),
        state=ResourceState(str(value["state"])),
        backend=str(value["backend"]),
        artifact=artifact,
        model_id=str(value["model_id"]) if value.get("model_id") is not None else None,
        tensor_ref=(
            str(value["tensor_ref"]) if value.get("tensor_ref") is not None else None
        ),
        training_fingerprint=(
            str(value["training_fingerprint"])
            if value.get("training_fingerprint") is not None
            else None
        ),
        metrics={str(key): float(item) for key, item in value.get("metrics", {}).items()},
        metadata=metadata,
    )
