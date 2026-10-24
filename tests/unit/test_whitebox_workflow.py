"""白盒工作流配置和预检测试。"""

import json
from pathlib import Path

import pytest

from warden.infrastructure.workflows import (
    load_whitebox_probe_config,
    preflight_whitebox_probe_experiment,
)


def _write_dataset(path: Path) -> None:
    """写入满足三分合同的最小 JSONL 数据集。"""

    rows = []
    for split_index, split in enumerate(("train", "validation", "test")):
        for label in (0, 1):
            rows.append(
                {
                    "sample_id": f"{split}-{label}",
                    "family_id": f"family-{split_index}-{label}",
                    "split": split,
                    "label": label,
                    "inputs_by_agent": {
                        "sender": f"sender {split} {label}",
                        "receiver": f"receiver {split} {label}",
                    },
                }
            )
    path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n",
        encoding="utf-8",
    )


def test_config_resolves_paths_and_preflight_reports_missing_snapshot(tmp_path: Path) -> None:
    """预检不得下载模型，并应明确报告本地快照缺失。"""

    _write_dataset(tmp_path / "interactions.jsonl")
    config_path = tmp_path / "experiment.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "warden.whitebox-probe-experiment/1",
                "experiment_id": "test-whitebox",
                "model_id": "test/model",
                "model": {
                    "model_path": "models/missing",
                    "device": "cpu",
                    "dtype": "float32",
                    "local_files_only": True,
                },
                "dataset_path": "interactions.jsonl",
                "output_directory": "outputs/run-1",
                "agent_ids": ["sender", "receiver"],
                "capture_targets": [
                    {
                        "target_id": "layer-1",
                        "agent_ids": ["sender", "receiver"],
                        "layer": 1,
                    }
                ],
                "probe": {"random_seed": 7},
            }
        ),
        encoding="utf-8",
    )
    config = load_whitebox_probe_config(config_path)
    assert config.dataset_path == (tmp_path / "interactions.jsonl").resolve()
    assert config.model.model_path == str((tmp_path / "models" / "missing").resolve())
    report = preflight_whitebox_probe_experiment(config)
    assert report["ready"] is False
    model_check = next(
        item for item in report["checks"] if item["check_id"] == "model.local_snapshot"
    )
    assert model_check["status"] == "blocked"
    dataset_check = next(
        item for item in report["checks"] if item["check_id"] == "dataset.contract"
    )
    assert dataset_check["status"] == "pass"


def test_config_rejects_variable_width_all_token_policy(tmp_path: Path) -> None:
    """Probe Corpus 应拒绝可能随输入长度变化的全 token 特征。"""

    config_path = tmp_path / "all-token.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "warden.whitebox-probe-experiment/1",
                "experiment_id": "test-all-token",
                "model_id": "test/model",
                "model": {"model_path": "models/local"},
                "dataset_path": "interactions.jsonl",
                "output_directory": "outputs/run-1",
                "agent_ids": ["sender"],
                "capture_targets": [
                    {
                        "target_id": "layer-1",
                        "agent_ids": ["sender"],
                        "layer": 1,
                        "token_policy": "all",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="不支持 all token_policy"):
        load_whitebox_probe_config(config_path)
