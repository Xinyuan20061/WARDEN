"""使用既有 StegoPot 变换构造明确的信道实验臂。"""

from typing import Any


def channel_transform(method: str, *, search: str = "", replacement: str = "") -> Any:
    """返回官方信道变换；边选择仍由 StegoPot 实验配置负责。

    参数：
        method: message_block 或 message_replace。
        search: replace 必需的非空匹配文本。
        replacement: 预注册的替换文本，不接受中央秘密标签。

    返回：
        StegoPot BlockChannel 或 ReplaceChannel；未知方法抛 ValueError。
    """
    from stegopot.infrastructure.substrates.transforms import BlockChannel, ReplaceChannel

    if method == "message_block":
        return BlockChannel()
    if method == "message_replace":
        return ReplaceChannel(search, replacement)
    raise ValueError("未知信道干预方法")


def scoped_channel_transform(
    method: str, *, source: str, target: str, search="RED", replacement="BLUE"
) -> Any:
    """只选择冻结消息边；正文变换仍交给官方 Channel，不改变其他多跳边。"""
    inner = channel_transform(method, search=search, replacement=replacement)

    class ScopedChannel:
        def transform(self, message):
            if message.sender == source and message.recipient == target:
                return inner.transform(message)
            return message

    return ScopedChannel()
