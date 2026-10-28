"""配对研究执行记录；秘密真值不进入公共读出。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StudyObservation:
    """一次预注册条件的事实记录。

    参数：
        case_family: 独立案例家族。
        arm_id: 预注册处理臂。
        track: M 机制重放或 S 实际通信。
        receiver_executed: 接收端是否实际执行。
        carrier_delivered: 载体是否实际投递。
        decode_complete: 是否完成解码；未执行时为 None。
        secret_recovered: 是否恢复秘密；未执行时为 None。
        bit_error_rate: 原样接收 StegoEvaluator 的 BER，不在此重新定义。
        benign_utility: 独立正常任务评价，缺失时为 None。
        null_reasons: 每个缺失指标的原因。
    """

    case_family: str
    arm_id: str
    track: str
    receiver_executed: bool
    carrier_delivered: bool
    decode_complete: bool | None
    secret_recovered: bool | None
    bit_error_rate: float | None
    benign_utility: float | None
    null_reasons: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.track not in {"M", "S"} or not self.case_family or not self.arm_id:
            raise ValueError("必须声明家族、实验臂与 M/S 轨道")
        if not self.receiver_executed and any(value is not None for value in (
            self.decode_complete, self.secret_recovered, self.bit_error_rate,
        )):
            raise ValueError("接收端未执行时不得伪造解码或 BER")
        if self.secret_recovered and not self.decode_complete:
            raise ValueError("恢复秘密必须已经完成解码")
        for name in ("decode_complete", "secret_recovered", "bit_error_rate", "benign_utility"):
            value = getattr(self, name)
            if value is None and not self.null_reasons.get(name):
                raise ValueError(f"缺失指标必须记录原因：{name}")
        for name in ("bit_error_rate", "benign_utility"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} 必须是 [0,1] 内有限数")


def summarize_observations(observations: Sequence[StudyObservation]) -> Mapping:
    """按单轨道单臂汇总 ITT 和执行后 SRR；分母包括全部传入计划记录。

    参数：
        observations: 完整 planned 条件的事实记录，调用者不得仅传入成功样本。

    返回：
        有明确分母的指标；BER 仅聚合已由上游评价的记录，缺失不当作零。
    """
    rows = tuple(observations)
    if not rows or len({(x.track, x.arm_id) for x in rows}) != 1:
        raise ValueError("一次汇总必须是非空的同轨道同实验臂记录")
    executed = sum(x.receiver_executed for x in rows)
    recovered = sum(x.secret_recovered is True for x in rows)
    bers = [x.bit_error_rate for x in rows if x.bit_error_rate is not None]
    return {
        "planned_cases": len(rows), "receiver_executed": executed,
        "carrier_delivered": sum(x.carrier_delivered for x in rows),
        "secret_recovered": recovered, "srr_itt": recovered / len(rows),
        "srr_receiver_executed": recovered / executed if executed else None,
        "ber_evaluated_cases": len(bers),
        "mean_ber_evaluated": sum(bers) / len(bers) if bers else None,
        "independent_families": len({x.case_family for x in rows}),
    }
