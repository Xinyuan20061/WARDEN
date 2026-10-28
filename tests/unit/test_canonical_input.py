"""规范响应渲染边界；不下载模型或分词器。"""

from types import SimpleNamespace

import pytest

from warden.infrastructure.adapters.canonical_input import (
    encode_canonical_text,
    render_canonical_input,
)
from warden.infrastructure.adapters.stegopot_features import StegoPotActivationFeatureExtractor


class _Tokenizer:
    all_special_tokens = ["<eos>"]
    all_special_ids = [999]

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt, enable_thinking):
        assert not tokenize and add_generation_prompt and not enable_thinking
        return "USER:" + messages[0]["content"] + "<eos>\nASSISTANT:"

    def encode(self, text, *, add_special_tokens):
        assert not add_special_tokens
        if text.endswith("<eos>"):
            return [1, 999]
        return list(text.encode())


def test_response_is_in_assistant_and_coordinate_is_content_token():
    value = render_canonical_input(_Tokenizer(), "公开任务", '{"ack":"READY"}',
                                   tokenizer_revision="fixed")
    assert value.text.endswith('ASSISTANT:{"ack":"READY"}')
    assert value.token_ids[-1] == ord("}")
    assert value.coordinate()["token_index"] == len(value.token_ids) - 1
    assert value.coordinate()["tokenizer_revision"] == "fixed"


@pytest.mark.parametrize("text", ["response<eos>", "response\n"])
def test_special_end_or_trailing_newline_cannot_be_content_coordinate(text):
    with pytest.raises(ValueError):
        encode_canonical_text(_Tokenizer(), text)


def test_response_cannot_inject_special_token():
    with pytest.raises(ValueError, match="特殊"):
        render_canonical_input(_Tokenizer(), "task", "<eos>", tokenizer_revision="fixed")


def test_extractor_checks_exact_coordinate_and_revision():
    tokenizer = _Tokenizer()
    prepared = render_canonical_input(tokenizer, "task", "{}", tokenizer_revision="fixed")
    extractor = StegoPotActivationFeatureExtractor(
        {"receiver": SimpleNamespace(adapter=SimpleNamespace(model_id="tiny"))},
        input_tokenizer=tokenizer, tokenizer_revision="fixed",
    )
    extractor.validate_canonical_input(prepared.text, prepared.coordinate())
    with pytest.raises(ValueError, match="不一致"):
        extractor.validate_canonical_input(prepared.text,
                                            {**prepared.coordinate(), "token_id": 1})
    with pytest.raises(ValueError, match="不一致"):
        extractor.validate_canonical_input(
            prepared.text, {**prepared.coordinate(), "tokenizer_revision": "other"}
        )
