"""多智能体运行时事件端口。"""

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from warden.core.domain.models import CapabilityReport


class RuntimeAdapter(Protocol):
    """把外部 Agent 编排器的事件规范化为 WARDEN 协调轨迹。"""

    def capabilities(self) -> CapabilityReport:
        """返回消息、调用和回放能力。"""
        ...

    def run(self, contract_id: str, *, seed: int) -> Iterable[Mapping[str, Any]]:
        """运行一个场景并按发生顺序产生标准化事件。"""
        ...

    def close(self) -> None:
        """释放运行时拥有的资源。"""
        ...
