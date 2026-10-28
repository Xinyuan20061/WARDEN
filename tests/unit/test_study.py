"""未执行接收端与真实错误解码的分母不能混淆。"""

import pytest

from warden.core.domain.study import StudyObservation, summarize_observations


def test_ban_is_in_itt_but_not_ber_or_executed_denominator():
    absent = StudyObservation("f1", "ban", "S", False, False, None, None, None, 0.0,
                              {name: "receiver_not_executed" for name in (
                                  "decode_complete", "secret_recovered", "bit_error_rate")})
    summary = summarize_observations([absent])
    assert summary["srr_itt"] == 0
    assert summary["srr_receiver_executed"] is None
    assert summary["mean_ber_evaluated"] is None
    with pytest.raises(ValueError, match="不得伪造"):
        StudyObservation("f", "ban", "S", False, False, False, False, 1.0, 0.0)
