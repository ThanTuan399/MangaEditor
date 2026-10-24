from __future__ import annotations

import asyncio
import io
import re
import time
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

from .google_web import GoogleWebTranslator


class GoogleImageWebTranslator(GoogleWebTranslator):
    """Translate detected manga regions through Google Translate's Images mode.

    MangaEditor keeps ownership of detection, coordinates, inpainting and
    typesetting. For each detected text region this translator crops the
    original image, uploads that crop to Google Translate Images, clicks
    "Copy text", and maps the copied Vietnamese translation back to the same
    region index.

    This uses the public website, not an official Google Cloud API.
    """

    def __init__(self):
        super().__init__()
        self.crop_padding = 0.45
        self.min_side = 512
        self.fallback_to_text = True
        self._image_page_lang_pair: Optional[tuple[str, str]] = None
        self._image_cache: Dict[tuple[str, str, str], str] = {}

    def parse_args(self, config):
        super().parse_args(config)
        translator_config = self._resolve_translator_config(config)

        try:
            self.crop_padding = max(
                0.0,
                min(
                    2.0,
                    float(
                        self._get_config_value(
                            translator_config,
                            "google_image_crop_padding",
                            self.crop_padding,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            self.crop_padding = 0.45

        try:
            self.min_side = max(
                128,
                min(
                    1600,
                    int(
                        self._get_config_value(
                            translator_config,
                            "google_image_min_side",
                            self.min_side,
                        )
                    ),
                ),
            )
        except (TypeError, ValueError):
            self.min_side = 512

        self.fallback_to_text = bool(
            self._get_config_value(
                translator_config,
                "google_image_fallback_to_text",
                self.fallback_to_text,
            )
        )

    async def _start_browser(self):
        await super()._start_browser()
        if self._context is not None:
            try:
                await self._context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin="https://translate.google.com",
                )
            except Exception as exc:
                self.logger.debug(
                    f"Could not pre-grant clipboard permissions; "
                    f"will try browser clipboard normally: {exc}"
                )

    async def _stop_playwright(self):
        self._image_page_lang_pair = None
        await super()._stop_playwright()

    @staticmethod
    def _to_rgb_array(image: Any) -> np.ndarray:
        if isinstance(image, Image.Image):
            return np.asarray(image.convert("RGB"))

        array = np.asarray(image)
        if array.ndim == 2:
            return np.repeat(array[..., None], 3, axis=2)
        if array.ndim == 3 and array.shape[2] == 4:
            return array[..., :3]
        if array.ndim == 3 and array.shape[2] >= 3:
            return array[..., :3]
        raise ValueError(f"Unsupported image shape for Google image translation: {array.shape}")

    def _crop_region(self, image: Any, region: Any) -> np.ndarray:
        array = self._to_rgb_array(image)
        height, width = array.shape[:2]

        xyxy = getattr(region, "xyxy", None)
        if xyxy is None:
            raise ValueError("Text region has no bounding box")

        x1, y1, x2, y2 = [float(v) for v in np.asarray(xyxy).reshape(-1)[:4]]
        box_w = max(x2 - x1, 1.0)
        box_h = max(y2 - y1, 1.0)

        # Give Google's image OCR enough bubble/context around the text while
        # avoiding neighboring speech bubbles as much as possible.
        pad_x = max(12, int(round(box_w * self.crop_padding)))
        pad_y = max(12, int(round(box_h * self.crop_padding)))

        left = max(0, int(np.floor(x1)) - pad_x)
        top = max(0, int(np.floor(y1)) - pad_y)
        right = min(width, int(np.ceil(x2)) + pad_x)
        bottom = min(height, int(np.ceil(y2)) + pad_y)

        if right <= left or bottom <= top:
            raise ValueError(
                f"Invalid Google image crop: {(left, top, right, bottom)}"
            )

        crop = np.ascontiguousarray(array[top:bottom, left:right])

        crop_h, crop_w = crop.shape[:2]
        longest = max(crop_h, crop_w)
        if longest < self.min_side:
            scale = self.min_side / max(longest, 1)
            new_w = max(1, int(round(crop_w * scale)))
            new_h = max(1, int(round(crop_h * scale)))
            crop = np.asarray(
                Image.fromarray(crop.astype(np.uint8), mode="RGB").resize(
                    (new_w, new_h),
                    Image.Resampling.LANCZOS,
                )
            )

        return crop.astype(np.uint8, copy=False)

    def _crop_png_bytes(self, image: Any, region: Any) -> bytes:
        crop = self._crop_region(image, region)
        buffer = io.BytesIO()
        Image.fromarray(crop, mode="RGB").save(buffer, format="PNG")
        return buffer.getvalue()

    async def _ensure_image_page(self, source_code: str, target_code: str):
        await self._start_browser()
        pair = (source_code, target_code)

        if (
            self._image_page_lang_pair == pair
            and self._page is not None
            and "op=images" in (self._page.url or "")
        ):
            return

        url = (
            "https://translate.google.com/"
            f"?sl={source_code}&tl={target_code}&op=images"
        )
        await self._page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        await self._dismiss_consent()
        await self._locate_image_input()
        self._image_page_lang_pair = pair
        # The inherited text-page marker must not claim this is a text page.
        self._page_lang_pair = None

    async def _locate_image_input(self):
        inputs = self._page.locator('input[type="file"]')
        deadline = time.monotonic() + (self.timeout_ms / 1000.0)

        while time.monotonic() < deadline:
            self._check_cancelled()
            count = await inputs.count()
            for index in range(count):
                candidate = inputs.nth(index)
                accept = (await candidate.get_attribute("accept") or "").lower()
                if any(
                    token in accept
                    for token in ("image/", ".png", ".jpg", ".jpeg", ".webp")
                ):
                    return candidate

            await asyncio.sleep(0.15)

        raise RuntimeError(
            "Google Translate image upload input was not found. "
            "The website layout may have changed."
        )

    async def _clear_current_image(self):
        if self._page is None:
            return

        candidates = (
            self._page.get_by_role(
                "button",
                name=re.compile(r"clear\s*image", re.I),
            ).first,
            self._page.locator(
                '[aria-label*="Clear image"], [aria-label*="Clear Image"]'
            ).first,
        )

        for candidate in candidates:
            try:
                if await candidate.count() and await candidate.is_visible():
                    await candidate.click(timeout=2500)
                    await self._page.wait_for_timeout(200)
                    return
            except Exception:
                continue

    async def _locate_copy_text_button(self):
        candidates = (
            self._page.get_by_role(
                "button",
                name=re.compile(r"copy\s*text", re.I),
            ).first,
            self._page.locator(
                '[aria-label*="Copy text"], [aria-label*="Copy Text"]'
            ).first,
            self._page.get_by_text(
                re.compile(r"^Copy\s*text$", re.I)
            ).first,
        )

        deadline = time.monotonic() + (self.timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            self._check_cancelled()
            for candidate in candidates:
                try:
                    if await candidate.count() and await candidate.is_visible():
                        return candidate
                except Exception:
                    continue
            await asyncio.sleep(0.2)

        raise TimeoutError(
            "Google Translate Images did not expose the Copy text control "
            "before timeout."
        )

    async def _read_clipboard(self) -> str:
        try:
            value = await self._page.evaluate(
                "() => navigator.clipboard.readText()"
            )
            return str(value or "").strip()
        except Exception as exc:
            raise RuntimeError(
                "Could not read Google Translate's copied image translation "
                "from the browser clipboard."
            ) from exc

    async def _copy_translated_text(self) -> str:
        try:
            await self._page.evaluate(
                "() => navigator.clipboard.writeText('')"
            )
        except Exception:
            pass

        button = await self._locate_copy_text_button()
        await button.click()

        deadline = time.monotonic() + (self.timeout_ms / 1000.0)
        candidate = ""
        candidate_since = None

        while time.monotonic() < deadline:
            self._check_cancelled()
            value = await self._read_clipboard()
            now = time.monotonic()

            if value:
                if value != candidate:
                    candidate = value
                    candidate_since = now
                elif candidate_since is not None and now - candidate_since >= 0.45:
                    return re.sub(r"\s+", " ", candidate).strip()

            await asyncio.sleep(0.15)

        if candidate:
            return re.sub(r"\s+", " ", candidate).strip()

        raise TimeoutError(
            "Google Translate Images Copy text returned no translated text."
        )

    async def _translate_crop_once(
        self,
        source_code: str,
        target_code: str,
        query: str,
        image: Any,
        region: Any,
    ) -> str:
        png_bytes = self._crop_png_bytes(image, region)
        cache_key = (
            source_code,
            target_code,
            str(hash(png_bytes)),
        )
        cached = self._image_cache.get(cache_key)
        if cached is not None:
            return cached

        await self._respect_delay()
        await self._ensure_image_page(source_code, target_code)
        await self._clear_current_image()

        image_input = await self._locate_image_input()
        await image_input.set_input_files(
            files=[
                {
                    "name": "manga_region.png",
                    "mimeType": "image/png",
                    "buffer": png_bytes,
                }
            ]
        )

        result = await self._copy_translated_text()
        if not result:
            raise RuntimeError(
                f"Google Translate Images returned empty text for: {query!r}"
            )

        self._image_cache[cache_key] = result
        self._last_request_at = time.monotonic()
        self.logger.info(f"Google Image: {query} => {result}")
        return result

    def _resolve_image_items(
        self,
        queries: List[str],
        ctx: Any,
    ) -> List[Optional[dict]]:
        items = list(getattr(ctx, "google_image_items", None) or [])

        if not items:
            image = getattr(ctx, "img_rgb", None)
            regions = getattr(ctx, "text_regions", None) or []
            for region in regions:
                text = getattr(region, "text", None)
                if text is not None:
                    items.append(
                        {
                            "image": image,
                            "region": region,
                            "text": text,
                        }
                    )

        if len(items) == len(queries):
            return items

        # CommonTranslator may remove punctuation-only queries. Recover mapping
        # by scanning the original region texts in order.
        resolved: List[Optional[dict]] = []
        cursor = 0
        for query in queries:
            found = None
            while cursor < len(items):
                candidate = items[cursor]
                cursor += 1
                if str(candidate.get("text") or "") == str(query):
                    found = candidate
                    break
            resolved.append(found)
        return resolved

    async def _translate(
        self,
        from_lang: str,
        to_lang: str,
        queries: List[str],
        ctx=None,
    ) -> List[str]:
        if not queries:
            return []

        source_code = self._configured_source_code()
        if source_code == "auto":
            source_code = from_lang if from_lang != "auto" else "auto"
        target_code = to_lang

        image_items = self._resolve_image_items(queries, ctx)

        async with self._request_lock:
            results: List[str] = []

            for query, item in zip(queries, image_items):
                self._check_cancelled()

                if not item or item.get("image") is None or item.get("region") is None:
                    if self.fallback_to_text:
                        self.logger.warning(
                            f"No image region available for {query!r}; "
                            "falling back to Google text translation."
                        )
                        results.append(
                            await super()._translate_one(
                                source_code,
                                target_code,
                                query,
                            )
                        )
                        continue
                    raise RuntimeError(
                        f"No image region available for Google image translation: {query!r}"
                    )

                last_error = None
                translated = None

                for attempt in range(self.retries + 1):
                    try:
                        translated = await self._translate_crop_once(
                            source_code,
                            target_code,
                            query,
                            item["image"],
                            item["region"],
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                        self.logger.warning(
                            f"Google Image attempt {attempt + 1}/"
                            f"{self.retries + 1} failed for {query!r}: {exc}"
                        )
                        self._image_page_lang_pair = None
                        if attempt < self.retries:
                            await asyncio.sleep(min(1.0 + attempt, 3.0))

                if translated is None:
                    if not self.fallback_to_text:
                        raise RuntimeError(
                            f"Google image translation failed for {query!r}: "
                            f"{last_error}"
                        ) from last_error

                    self.logger.warning(
                        f"Google image translation failed for {query!r}; "
                        "falling back to Google text translation."
                    )
                    self._image_page_lang_pair = None
                    translated = await super()._translate_one(
                        source_code,
                        target_code,
                        query,
                    )

                results.append(translated)

            return results

    async def unload(self):
        self._image_cache.clear()
        await super().unload()
