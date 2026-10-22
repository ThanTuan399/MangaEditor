from manga_translator.config import Translator
from manga_translator.translators import TRANSLATORS
from manga_translator.translators.local_nllb import LocalNLLBTranslator


def test_local_nllb_is_registered():
    assert Translator.local_nllb in TRANSLATORS


def test_local_nllb_detects_supported_scripts_without_loading_model():
    translator = LocalNLLBTranslator()

    assert translator._detect_source_code("これはテストです") == "jpn_Jpan"
    assert translator._detect_source_code("这是一个测试") == "zho_Hans"
    assert translator._detect_source_code("這是一個測試") == "zho_Hant"
    assert translator._detect_source_code("This is a test") == "eng_Latn"


def test_local_nllb_explicit_source_hint_wins():
    translator = LocalNLLBTranslator()
    translator.source_lang = "JPN"
    assert translator._detect_source_code("東京") == "jpn_Jpan"

    translator.source_lang = "CHT"
    assert translator._detect_source_code("測試") == "zho_Hant"
