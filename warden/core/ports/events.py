"""运行事件发布端口。"""

from collections.abc import Mapping
from typing import Any, Protocol


class EventPublisher(Protocol):
    """向 API、日志或消息系统发布不含原始 Activation 的事件。"""

    def publish(self, event: Mapping[str, Any]) -> None:
        """同步接收一个已序列化事件。"""
        ...
