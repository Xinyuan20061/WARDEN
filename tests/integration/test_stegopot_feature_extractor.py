"""StegoPot 表征提取器的可选 PyTorch 合同测试。"""

from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("stegopot")

from warden.core.domain.models import CaptureTarget  # noqa: E402
from warden.infrastructure.adapters.stegopot_features import (  # noqa: E402
    StegoPotActivationFeatureExtractor,
)


class _FakeTrace:
    """按 TensorRef 返回测试记录。"""

    def __init__(self, values):
        self._values = values

    def get(self, ref):
        """返回与请求位置对应的张量记录。"""

        return SimpleNamespace(value=self._values[ref.key])


class _FakeRuntime:
    """保留 StegoPot ModelRuntime 调用形状的轻量替身。"""

    def __init__(self):
        self.adapter = SimpleNamespace(model_id="fake/torch-model")
        self.close_count = 0

    def forward(self, inputs, *, policy, run_id):
        """根据 token 选择返回末 token 或完整序列张量。"""

        del inputs, run_id
        values = {}
        for ref in policy.refs:
            if ref.token == -1:
                values[ref.key] = torch.tensor([[1.0, 2.0, 3.0]])
            else:
                values[ref.key] = torch.tensor(
                    [[[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]]
                )
        return SimpleNamespace(trace=_FakeTrace(values))

    def close(self):
        """记录生命周期关闭次数。"""

        self.close_count += 1


def test_shared_runtime_extracts_last_and_mean_token_features() -> None:
    """多个 Agent 应复用同一 Runtime，token 归约应保持明确。"""

    runtime = _FakeRuntime()
    extractor = StegoPotActivationFeatureExtractor(
        {"sender": runtime, "receiver": runtime},
        model_id="logical/model@revision",
        own_runtimes=True,
    )
    values = extractor.extract(
        sample_id="sample-1",
        inputs_by_agent={"sender": "a", "receiver": "b"},
        targets=(
            CaptureTarget(
                target_id="last",
                agent_ids=("sender", "receiver"),
                layer=1,
                token_policy="last_token",
            ),
            CaptureTarget(
                target_id="mean",
                agent_ids=("sender", "receiver"),
                layer=2,
                token_policy="mean_tokens",
            ),
        ),
    )
    assert extractor.model_id == "logical/model@revision"
    assert values["sender/last"].tolist() == [1.0, 2.0, 3.0]
    assert values["receiver/mean"].tolist() == [3.0, 4.0]
    extractor.close()
    extractor.close()
    assert runtime.close_count == 1
