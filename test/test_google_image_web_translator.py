import numpy as np

from manga_translator.config import Translator
from manga_translator.translators import TRANSLATORS
from manga_translator.translators.google_image_web import GoogleImageWebTranslator


class _Region:
    def __init__(self, xyxy, text="COME ON!"):
        self.xyxy = np.asarray(xyxy, dtype=np.float64)
        self.text = text


def test_google_image_is_registered():
    assert Translator.google_image_web in TRANSLATORS


def test_google_image_crop_has_padding_and_upscale():
    translator = GoogleImageWebTranslator()
    translator.crop_padding = 0.5
    translator.min_side = 512

    image = np.full((200, 300, 3), 255, dtype=np.uint8)
    region = _Region([100, 70, 160, 110])

    crop = translator._crop_region(image, region)

    assert crop.ndim == 3
    assert crop.shape[2] == 3
    assert max(crop.shape[:2]) >= 512


def test_google_image_resolve_items_keeps_query_order():
    translator = GoogleImageWebTranslator()
    image = np.full((50, 50, 3), 255, dtype=np.uint8)
    first = _Region([0, 0, 10, 10], "HELLO")
    second = _Region([10, 10, 20, 20], "WORLD")

    class _Ctx:
        google_image_items = [
            {"image": image, "region": first, "text": "HELLO"},
            {"image": image, "region": second, "text": "WORLD"},
        ]

    resolved = translator._resolve_image_items(["HELLO", "WORLD"], _Ctx())

    assert resolved[0]["region"] is first
    assert resolved[1]["region"] is second
