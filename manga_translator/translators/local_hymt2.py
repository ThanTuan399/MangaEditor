"""Offline Hy-MT2 translation through a locally running llama.cpp server.

This translator does not download or load GGUF weights in the Qt process.
Start llama-server separately, then select local_hymt2 in MangaEditor.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
from typing import List
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .common import CommonTranslator


class LocalHyMT2Translator(CommonTranslator):
    """Translate OCR regions one at a time, preserving their original order."""

    _LANGUAGE_CODE_MAP = {
        "JPN": "Japanese",
        "CHS": "Chinese",
        "CHT": "Traditional Chinese",
        "ENG": "English",
        "VIN": "Vietnamese",
    }

    def __init__(self):
        super().__init__()
        self.base_url = "http://127.0.0.1:8080/v1"
        self.model_name = "auto"
        self.source_lang = "JPN"
        self.timeout = 120
        self.max_output_tokens = 512
        self.context_regions = 0

    def parse_args(self, config):
        super().parse_args(config)
        settings = self._resolve_translator_config(config)
        get = self._get_config_value

        self.base_url = self._validate_base_url(
            str(get(settings, "hymt_api_base", self.base_url) or "").strip()
        )
        self.model_name = str(get(settings, "hymt_model", "auto") or "auto").strip()
        self.source_lang = str(get(settings, "hymt_source_lang", "JPN") or "JPN").upper()
        if self.source_lang not in {*self._LANGUAGE_CODE_MAP, "AUTO"}:
            raise ValueError("Hy-MT2 source language must be JPN, CHS, CHT, ENG or auto")
        self.timeout = max(5, min(600, int(get(settings, "hymt_timeout_seconds", 120))))
        self.max_output_tokens = max(
            32, min(4096, int(get(settings, "hymt_max_output_tokens", 512)))
        )
        self.context_regions = max(
            0, min(10, int(get(settings, "hymt_context_regions", 0)))
        )

    @staticmethod
    def _validate_base_url(value: str) -> str:
        """Only send manga dialogue to a local server, never to an external host."""
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path.rstrip("/") not in {"", "/v1"}
        ):
            raise ValueError(
                "Hy-MT2 API must be a local address, e.g. http://127.0.0.1:8080/v1"
            )
        # Accessing .port also validates the port's syntax.
        _ = parts.port
        return value.rstrip("/") + ("/v1" if not parts.path.rstrip("/") else "")

    def _request_json(self, method: str, endpoint: str, payload=None) -> dict:
        url = self.base_url.rstrip("/") + endpoint
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8")
        req = Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urlopen(req, timeout=self.timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Hy-MT2 server returned HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise RuntimeError(
                f"Cannot reach local Hy-MT2 at {self.base_url}. "
                "Start llama-server and keep its PowerShell window open. "
                f"Details: {exc}"
            ) from exc
        if not isinstance(result, dict):
            raise RuntimeError("Hy-MT2 returned an invalid JSON response")
        return result

    def _resolve_model_name(self) -> str:
        if self.model_name and self.model_name.lower() != "auto":
            return self.model_name
        models = self._request_json("GET", "/models").get("data", [])
        if not isinstance(models, list) or not models or not isinstance(models[0], dict):
            raise RuntimeError(
                "No model is loaded in llama-server. Start it with "
                "llama-server -hf tencent/Hy-MT2-1.8B-GGUF:Q4_K_M --port 8080"
            )
        model = str(models[0].get("id") or "").strip()
        if not model:
            raise RuntimeError("llama-server did not return a model ID")
        return model

    def _get_source_name(self, text: str, from_lang: str) -> str:
        if self.source_lang != "AUTO":
            return self._LANGUAGE_CODE_MAP[self.source_lang]
        if from_lang != "auto":
            return from_lang
        if re.search(r"[\u3040-\u30ff]", text):
            return "Japanese"
        if re.search(r"[\u3400-\u9fff]", text):
            # Pure Han text is ambiguous; Japanese is safer for manga by default.
            return "Japanese"
        return "English"

    def _translate_sync(self, from_lang: str, to_lang: str, queries: List[str]) -> List[str]:
        self._check_cancelled()
        model = self._resolve_model_name()
        translations: List[str] = []
        previous: List[str] = []
        for original in queries:
            self._check_cancelled()
            text = str(original or "")
            if not text.strip():
                translations.append(text)
                continue
            source_name = self._get_source_name(text, from_lang)
            if source_name == to_lang:
                translations.append(text)
                previous.append(text)
                continue

            context = ""
            if self.context_regions and previous:
                context = (
                    "Previous dialogue for context only (do not translate it):\n"
                    + "\n".join(previous[-self.context_regions:])
                    + "\n\n"
                )
            prompt = (
                context
                + f"Translate the following segment from {source_name} into "
                + f"{to_lang}, without additional explanation:\n\n{text}"
            )
            result = self._request_json(
                "POST",
                "/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": 0.7,
                    "top_p": 0.6,
                    "top_k": 20,
                    "repeat_penalty": 1.05,
                    "max_tokens": self.max_output_tokens,
                },
            )
            choices = result.get("choices") or []
            if not isinstance(choices, list) or not choices:
                raise RuntimeError("Hy-MT2 returned no translation choices")
            choice = choices[0]
            if not isinstance(choice, dict):
                raise RuntimeError("Hy-MT2 returned an invalid translation choice")
            if choice.get("finish_reason") == "length":
                raise RuntimeError(
                    "Hy-MT2 translation was truncated. Increase max output tokens."
                )
            message = choice.get("message") or {}
            translated = message.get("content") if isinstance(message, dict) else None
            if not isinstance(translated, str) or not translated.strip():
                raise RuntimeError("Hy-MT2 returned an empty translation")
            translations.append(translated.strip())
            previous.append(text)
        return translations

    async def _translate(self, from_lang: str, to_lang: str, queries: List[str], ctx=None) -> List[str]:
        if not queries:
            return []
        return await asyncio.to_thread(
            self._translate_sync, from_lang, to_lang, list(queries)
        )

    async def unload(self):
        """llama-server owns model memory; this client has nothing to unload."""
        return None
