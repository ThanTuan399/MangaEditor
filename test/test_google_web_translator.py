from manga_translator.config import Translator
from manga_translator.translators import TRANSLATORS
from manga_translator.translators.google_web import GoogleWebTranslator


def test_google_web_is_registered():
    assert Translator.google_web in TRANSLATORS


def test_google_web_ocr_normalization():
    translator = GoogleWebTranslator()
    assert translator._normalize_ocr_text("BEAUTI-\nFUL STARS!") == "BEAUTIFUL STARS!"
    assert translator._normalize_ocr_text("HELLO\nWORLD") == "HELLO WORLD"


def test_google_web_source_language_mapping():
    translator = GoogleWebTranslator()

    translator.source_lang = "ENG"
    assert translator._configured_source_code() == "en"

    translator.source_lang = "JPN"
    assert translator._configured_source_code() == "ja"

    translator.source_lang = "CHS"
    assert translator._configured_source_code() == "zh-CN"

    translator.source_lang = "CHT"
    assert translator._configured_source_code() == "zh-TW"

    translator.source_lang = "auto"
    assert translator._configured_source_code() == "auto"
