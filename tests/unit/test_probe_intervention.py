"""Probe 风险方向干预工具测试。"""

import pytest

numpy = pytest.importorskip("numpy")

from warden.infrastructure.methods.intervention import (  # noqa: E402
    directional_shift,
    split_joint_probe_direction,
)


def test_split_joint_direction_preserves_stream_order() -> None:
    """联合权重应严格按训练清单中的特征流顺序拆分。"""

    parts = split_joint_probe_direction(
        numpy.asarray([1.0, 2.0, 3.0, 4.0, 5.0]),
        stream_ids=("sender/layer-4", "receiver/layer-4"),
        stream_widths={"sender/layer-4": 2, "receiver/layer-4": 3},
    )
    assert parts["sender/layer-4"].tolist() == [1.0, 2.0]
    assert parts["receiver/layer-4"].tolist() == [3.0, 4.0, 5.0]


def test_directional_shift_has_bounded_requested_norm() -> None:
    """单位方向平移的范数应等于请求幅度。"""

    value = numpy.asarray([2.0, 1.0, -1.0], dtype=numpy.float32)
    shifted = directional_shift(value, numpy.asarray([3.0, 4.0, 0.0]), amplitude=0.25)
    assert float(numpy.linalg.norm(value - shifted)) == pytest.approx(0.25, abs=1e-6)
