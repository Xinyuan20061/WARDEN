"""固定 assistant 响应的模型专用渲染与末 token 核验。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

CANONICAL_PROTOCOL = "assistant_canonical_response:last_non_special_token/1"


@dataclass(frozen=True, slots=True)
class CanonicalInput:
    """规范输入及其实际坐标，禁止从标签推断位置。

    参数：
        text: 完整聊天前缀及固定 assistant 响应，不追加结束标记。
        token_ids: 对 text 使用 add_special_tokens=False 得到的精确序列。
        tokenizer_revision: 已固定的分词器版本。
    """

    text: str
    token_ids: tuple[int, ...]
    tokenizer_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_ids", tuple(self.token_ids))
        if not self.text or not self.token_ids or not self.tokenizer_revision:
            raise ValueError("规范输入、token 序列和分词器版本必须非空")
        if any(type(value) is not int or value < 0 for value in self.token_ids):
            raise ValueError("规范输入 token_ids 必须是非负整数序列")

    def coordinate(self) -> dict[str, Any]:
        """返回不包含上下文原文的末 token 坐标与输入指纹。"""
        return {
            "protocol": CANONICAL_PROTOCOL,
            "tokenizer_revision": self.tokenizer_revision,
            "token_index": len(self.token_ids) - 1,
            "token_id": self.token_ids[-1],
            "token_count": len(self.token_ids),
            "input_sha256": sha256(self.text.encode()).hexdigest(),
        }


def render_canonical_input(tokenizer: Any, user_prompt: str, response: str,
                           *, tokenizer_revision: str) -> CanonicalInput:
    """把固定响应放在 assistant 前缀后，验证它贡献了末内容 token。

    参数：
        tokenizer: 支持 apply_chat_template 的已加载分词器，不转移所有权。
        user_prompt: 仅包含授权上下文和采集提示的 user 文本。
        response: 官方合同规定的固定 assistant 响应，不能包含特殊 token。
        tokenizer_revision: 分词器固定版本，写入坐标清单。

    返回：
        末 token 已验证的 CanonicalInput。

    异常：
        ValueError: 模板缺失、固定响应为空或含特殊 token。
    """
    if not isinstance(response, str) or not response.strip():
        raise ValueError("固定 assistant 响应必须非空")
    if any(token and token in response for token in tokenizer.all_special_tokens):
        raise ValueError("固定响应不能包含特殊 token")
    prefix = tokenizer.apply_chat_template(
        [{"role": "user", "content": user_prompt}], tokenize=False,
        add_generation_prompt=True, enable_thinking=False,
    )
    text = prefix + response
    ids = encode_canonical_text(tokenizer, text)
    if len(ids) <= len(tokenizer.encode(prefix, add_special_tokens=False)):
        raise ValueError("固定 assistant 响应没有贡献可采集 token")
    return CanonicalInput(text, ids, tokenizer_revision)


def encode_canonical_text(tokenizer: Any, text: str) -> tuple[int, ...]:
    """不追加 BOS/EOS 地编码 text；末 token 特殊或末尾空白时拒绝采集。"""
    if text != text.rstrip():
        raise ValueError("规范响应末尾不能是空白，须显式给出内容边界")
    ids = tuple(tokenizer.encode(text, add_special_tokens=False))
    if not ids or ids[-1] in tokenizer.all_special_ids:
        raise ValueError("规范采集点必须是非特殊内容 token")
    return ids
