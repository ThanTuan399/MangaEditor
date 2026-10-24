from __future__ import annotations

import asyncio
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode

from .common import CommonTranslator


class GoogleWebTranslator(CommonTranslator):
    """Automate the public Google Translate website with a real browser.

    This backend does not use a Google Cloud/Gemini API key. It requires an
    Internet connection and a supported local browser. Because it automates a
    website UI, Google can change the DOM at any time; selector fallbacks are
    intentionally centralized in this class.
    """

    _LANGUAGE_CODE_MAP = {
        "JPN": "ja",
        "CHS": "zh-CN",
        "CHT": "zh-TW",
        "ENG": "en",
        "VIN": "vi",
    }

    _SOURCE_BOX_SELECTORS = (
        'textarea[aria-label="Source text"]',
        'textarea[aria-label*="Source"]',
        'textarea',
    )

    _RESULT_SELECTORS = (
        'span[jsname="W297wb"]',
        'span[jsname="jqKxS"]',
        '[data-language-for-alternatives] span',
    )

    def __init__(self):
        super().__init__()
        self.source_lang = "auto"
        self.browser_channel = "auto"
        self.headless = True
        self.delay_ms = 900
        self.timeout_ms = 20000
        self.retries = 2

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._page_lang_pair: Optional[tuple[str, str]] = None
        self._request_lock = asyncio.Lock()
        self._cache: Dict[tuple[str, str, str], str] = {}
        self._last_request_at = 0.0

    def parse_args(self, config):
        super().parse_args(config)
        translator_config = self._resolve_translator_config(config)

        source = str(
            self._get_config_value(
                translator_config,
                "google_web_source_lang",
                self.source_lang,
            )
            or "auto"
        ).strip().upper()
        self.source_lang = "auto" if source == "AUTO" else source

        browser = str(
            self._get_config_value(
                translator_config,
                "google_web_browser",
                self.browser_channel,
            )
            or "auto"
        ).strip().lower()
        self.browser_channel = (
            browser
            if browser in {"auto", "msedge", "chrome", "chromium"}
            else "auto"
        )

        self.headless = bool(
            self._get_config_value(
                translator_config,
                "google_web_headless",
                self.headless,
            )
        )
        self.delay_ms = max(
            0,
            int(
                self._get_config_value(
                    translator_config,
                    "google_web_delay_ms",
                    self.delay_ms,
                )
                or 0
            ),
        )
        self.timeout_ms = max(
            5000,
            int(
                self._get_config_value(
                    translator_config,
                    "google_web_timeout_ms",
                    self.timeout_ms,
                )
                or self.timeout_ms
            ),
        )
        self.retries = max(
            0,
            int(
                self._get_config_value(
                    translator_config,
                    "google_web_retries",
                    self.retries,
                )
                or 0
            ),
        )

    def _configured_source_code(self) -> str:
        if self.source_lang == "auto":
            return "auto"
        return self._LANGUAGE_CODE_MAP.get(self.source_lang, "auto")

    @staticmethod
    def _normalize_ocr_text(text: str) -> str:
        value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", value)
        value = re.sub(r"\s*\n+\s*", " ", value)
        value = re.sub(r"[ \t]+", " ", value)
        return value.strip()

    async def _start_browser(self):
        if self._browser is not None and self._page is not None:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Google Translate (Web) requires Playwright. "
                "Install project dependencies or run: python -m pip install playwright"
            ) from exc

        self._playwright = await async_playwright().start()

        candidates = (
            ("msedge", "chrome", "chromium")
            if self.browser_channel == "auto"
            else (self.browser_channel,)
        )

        errors = []
        for channel in candidates:
            try:
                kwargs = {"headless": self.headless}
                if channel != "chromium":
                    kwargs["channel"] = channel
                self._browser = await self._playwright.chromium.launch(**kwargs)
                self.logger.info(
                    f"Google Translate Web browser started: {channel}, "
                    f"headless={self.headless}"
                )
                break
            except Exception as exc:
                errors.append(f"{channel}: {exc}")
                self._browser = None

        if self._browser is None:
            await self._stop_playwright()
            joined = " | ".join(errors)
            raise RuntimeError(
                "Could not start a browser for Google Translate (Web). "
                "Microsoft Edge is preferred on Windows. "
                "If Edge/Chrome is unavailable, install Playwright Chromium with "
                "'python -m playwright install chromium'. "
                f"Details: {joined}"
            )

        self._context = await self._browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        self._page_lang_pair = None

    async def _stop_playwright(self):
        page, context, browser, playwright = (
            self._page,
            self._context,
            self._browser,
            self._playwright,
        )
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._page_lang_pair = None

        for obj in (page, context, browser):
            if obj is None:
                continue
            try:
                await obj.close()
            except Exception:
                pass

        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    async def _dismiss_consent(self):
        if self._page is None:
            return

        labels = (
            re.compile(r"Reject all", re.I),
            re.compile(r"I agree", re.I),
            re.compile(r"Accept all", re.I),
        )
        for label in labels:
            try:
                button = self._page.get_by_role("button", name=label).first
                if await button.count() and await button.is_visible():
                    await button.click(timeout=2500)
                    await self._page.wait_for_timeout(250)
                    return
            except Exception:
                continue

    async def _ensure_page(self, source_code: str, target_code: str):
        await self._start_browser()
        pair = (source_code, target_code)
        if self._page_lang_pair == pair and self._page is not None:
            return

        query = urlencode(
            {
                "sl": source_code,
                "tl": target_code,
                "op": "translate",
            }
        )
        url = f"https://translate.google.com/?{query}"

        try:
            await self._page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            await self._dismiss_consent()
            await self._locate_source_box()
            self._page_lang_pair = pair
        except Exception:
            self._page_lang_pair = None
            raise

    async def _locate_source_box(self):
        last_error = None

        for selector in self._SOURCE_BOX_SELECTORS:
            try:
                locator = self._page.locator(selector).first
                await locator.wait_for(state="visible", timeout=4000)
                return locator
            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "Google Translate source text box was not found. "
            "The website layout may have changed."
        ) from last_error

    async def _read_result_once(self) -> str:
        for selector in self._RESULT_SELECTORS:
            try:
                locator = self._page.locator(selector)
                count = await locator.count()
                if count <= 0:
                    continue

                parts = []
                for index in range(count):
                    item = locator.nth(index)
                    try:
                        if not await item.is_visible():
                            continue
                        value = (await item.inner_text()).strip()
                    except Exception:
                        continue

                    if value and (not parts or parts[-1] != value):
                        parts.append(value)

                result = " ".join(parts).strip()
                if result:
                    return result
            except Exception:
                continue

        return ""

    async def _wait_for_result(self, old_result: str) -> str:
        deadline = time.monotonic() + (self.timeout_ms / 1000.0)
        first_nonempty_at = None
        latest = ""

        while time.monotonic() < deadline:
            self._check_cancelled()
            latest = await self._read_result_once()

            if latest:
                if latest != old_result:
                    return latest

                if first_nonempty_at is None:
                    first_nonempty_at = time.monotonic()

                if time.monotonic() - first_nonempty_at >= 1.25:
                    return latest

            await asyncio.sleep(0.2)

        if latest:
            return latest

        raise TimeoutError(
            "Google Translate Web did not produce translated text before timeout."
        )

    async def _respect_delay(self):
        if self.delay_ms <= 0:
            return

        elapsed_ms = (time.monotonic() - self._last_request_at) * 1000.0
        remaining_ms = self.delay_ms - elapsed_ms
        if remaining_ms > 0:
            await asyncio.sleep(remaining_ms / 1000.0)

    async def _translate_one(
        self,
        source_code: str,
        target_code: str,
        text: str,
    ) -> str:
        normalized = self._normalize_ocr_text(text)
        if not normalized:
            return ""

        cache_key = (source_code, target_code, normalized)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        last_error = None

        for attempt in range(self.retries + 1):
            self._check_cancelled()

            try:
                await self._respect_delay()
                await self._ensure_page(source_code, target_code)

                source_box = await self._locate_source_box()
                old_result = await self._read_result_once()

                await source_box.fill("")
                await self._page.wait_for_timeout(120)
                await source_box.fill(normalized)

                result = await self._wait_for_result(old_result)
                result = re.sub(r"\s+", " ", result).strip()

                if not result:
                    raise RuntimeError("Google Translate Web returned empty text.")

                self._cache[cache_key] = result
                self._last_request_at = time.monotonic()
                self.logger.info(f"Google Web: {normalized} => {result}")
                return result

            except Exception as exc:
                last_error = exc
                self.logger.warning(
                    f"Google Translate Web attempt {attempt + 1}/"
                    f"{self.retries + 1} failed: {exc}"
                )
                self._page_lang_pair = None

                if self._page is not None:
                    try:
                        await self._page.reload(
                            wait_until="domcontentloaded",
                            timeout=self.timeout_ms,
                        )
                    except Exception:
                        await self._stop_playwright()

                if attempt < self.retries:
                    await asyncio.sleep(min(1.0 + attempt, 3.0))

        raise RuntimeError(
            f"Google Translate Web failed after {self.retries + 1} attempt(s): "
            f"{last_error}"
        ) from last_error

    async def _translate(
        self,
        from_lang: str,
        to_lang: str,
        queries: List[str],
        ctx=None,
    ) -> List[str]:
        del ctx

        if not queries:
            return []

        source_code = self._configured_source_code()
        if source_code == "auto":
            source_code = from_lang if from_lang != "auto" else "auto"

        target_code = to_lang

        async with self._request_lock:
            results = []
            for query in queries:
                results.append(
                    await self._translate_one(
                        source_code,
                        target_code,
                        query,
                    )
                )
            return results

    async def unload(self):
        await self._stop_playwright()
        self._cache.clear()
        self.logger.info("Google Translate Web browser closed.")
