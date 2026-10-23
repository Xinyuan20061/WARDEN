"""威胁契约来源端口。"""

from collections.abc import Sequence
from typing import Protocol

from warden.core.domain.models import CapabilityReport, ThreatContract


class ThreatContractSource(Protocol):
    """从基准或业务系统加载可审计威胁契约。"""

    def capabilities(self) -> CapabilityReport:
        """返回来源是否可用以及支持的契约能力。"""
        ...

    def list_contracts(self) -> Sequence[str]:
        """返回可加载的稳定契约标识。"""
        ...

    def load(self, contract_id: str) -> ThreatContract:
        """加载一个威胁契约。"""
        ...
