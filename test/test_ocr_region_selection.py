from types import SimpleNamespace

from manga_translator.mask_refinement.ocr_region_selection import regions_to_replace


def test_manual_render_only_replaces_regions_with_translation():
    untranslated = SimpleNamespace(text="Stay", translation="")
    translated = SimpleNamespace(text="Hello", translation="Xin chào")
    second = SimpleNamespace(text="Bye", translation="Tạm biệt")
    assert regions_to_replace([untranslated, translated, second]) == [translated, second]
    assert untranslated.translation == ""


def test_whitespace_only_translation_does_not_erase_ocr():
    whitespace = SimpleNamespace(text="Hello", translation="  \n")
    assert regions_to_replace([whitespace]) == []
