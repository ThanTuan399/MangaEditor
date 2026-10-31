import _bootstrap  # noqa: F401

import pytest

from manga_translator.config import Translator
from manga_translator.translators import TRANSLATORS
from manga_translator.translators.local_hymt2 import LocalHyMT2Translator


def test_hymt2_registered_separately_from_nllb():
    assert Translator.local_hymt2 in TRANSLATORS
    assert TRANSLATORS[Translator.local_hymt2] is LocalHyMT2Translator
    assert Translator.local_nllb in TRANSLATORS


def test_hymt2_api_accepts_only_local_addresses():
    assert LocalHyMT2Translator._validate_base_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080/v1"
    assert LocalHyMT2Translator._validate_base_url("http://localhost:8080/v1") == "http://localhost:8080/v1"
    with pytest.raises(ValueError):
        LocalHyMT2Translator._validate_base_url("https://example.com/v1")
    with pytest.raises(ValueError):
        LocalHyMT2Translator._validate_base_url("http://127.0.0.1.evil.com/v1")


def test_hymt2_source_language_hint_wins():
    translator = LocalHyMT2Translator()
    assert translator._get_source_name("東京", "auto") == "Japanese"
    translator.source_lang = "CHT"
    assert translator._get_source_name("東京", "auto") == "Traditional Chinese"
    translator.source_lang = "AUTO"
    assert translator._get_source_name("これは", "auto") == "Japanese"


def test_hymt2_keeps_ocr_region_order_and_skips_empty(monkeypatch):
    translator = LocalHyMT2Translator()
    prompts = []

    monkeypatch.setattr(translator, "_check_cancelled", lambda: None)

    def fake_request(method, endpoint, payload=None):
        if endpoint == "/models":
            return {"data": [{"id": "mock-local-gguf"}]}
        assert method == "POST"
        assert payload["model"] == "mock-local-gguf"
        assert payload["messages"][0]["role"] == "user"
        prompts.append(payload["messages"][0]["content"])
        return {"choices": [{"message": {"content": f"Ban dich {len(prompts)}"},
                             "finish_reason": "stop"}]}

    monkeypatch.setattr(translator, "_request_json", fake_request)
    result = translator._translate_sync("auto", "Vietnamese", ["こんにちは", "", "ありがとう"])
    assert result == ["Ban dich 1", "", "Ban dich 2"]
    assert "こんにちは" in prompts[0]
    assert "ありがとう" in prompts[1]


def test_hymt2_rejects_truncated_response(monkeypatch):
    translator = LocalHyMT2Translator()
    monkeypatch.setattr(translator, "_check_cancelled", lambda: None)

    def fake_request(method, endpoint, payload=None):
        if endpoint == "/models":
            return {"data": [{"id": "test"}]}
        return {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}

    monkeypatch.setattr(translator, "_request_json", fake_request)
    with pytest.raises(RuntimeError, match="truncated"):
        translator._translate_sync("auto", "Vietnamese", ["こんにちは"])
