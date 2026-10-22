from __future__ import annotations

import asyncio
import os
import re
import threading
from collections import defaultdict
from typing import Any, Dict, List

import py3langid as langid

from ..utils import BASE_PATH
from .common import CommonTranslator


class LocalNLLBTranslator(CommonTranslator):
    """Offline NLLB translator for Japanese/Chinese/English -> Vietnamese.

    The model is downloaded by Transformers on first use unless local_model_path
    is set or local_files_only=True. After the model exists in the local cache,
    translation does not require an API key or network connection.
    """

    _LANGUAGE_CODE_MAP = {
        "JPN": "jpn_Jpan",
        "CHS": "zho_Hans",
        "CHT": "zho_Hant",
        "ENG": "eng_Latn",
        "VIN": "vie_Latn",
    }

    _MODEL_CACHE: Dict[str, tuple[Any, Any, str]] = {}
    _CACHE_LOCK = threading.RLock()
    _INFERENCE_LOCK = threading.RLock()

    def __init__(self):
        super().__init__()
        self.model_name = "facebook/nllb-200-distilled-600M"
        self.model_path = None
        self.source_lang = "auto"
        self.device_preference = "auto"
        self.batch_size = 8
        self.max_input_tokens = 256
        self.max_new_tokens = 256
        self.num_beams = 3
        self.local_files_only = False
        self.use_gpu = True

    def parse_args(self, config):
        super().parse_args(config)
        translator_config = self._resolve_translator_config(config)

        self.model_name = str(
            self._get_config_value(
                translator_config,
                "local_model_name",
                self.model_name,
            )
            or self.model_name
        ).strip()
        self.model_path = self._get_config_value(
            translator_config,
            "local_model_path",
            self.model_path,
        )
        self.source_lang = str(
            self._get_config_value(
                translator_config,
                "local_source_lang",
                self.source_lang,
            )
            or "auto"
        ).strip().upper()
        if self.source_lang == "AUTO":
            self.source_lang = "auto"

        self.device_preference = str(
            self._get_config_value(
                translator_config,
                "local_device",
                self.device_preference,
            )
            or "auto"
        ).strip().lower()
        if self.device_preference not in {"auto", "cuda", "cpu"}:
            self.device_preference = "auto"

        self.batch_size = max(
            1,
            int(self._get_config_value(translator_config, "local_batch_size", self.batch_size) or 1),
        )
        self.max_input_tokens = max(
            32,
            int(
                self._get_config_value(
                    translator_config,
                    "local_max_input_tokens",
                    self.max_input_tokens,
                )
                or self.max_input_tokens
            ),
        )
        self.max_new_tokens = max(
            16,
            int(
                self._get_config_value(
                    translator_config,
                    "local_max_new_tokens",
                    self.max_new_tokens,
                )
                or self.max_new_tokens
            ),
        )
        self.num_beams = max(
            1,
            int(self._get_config_value(translator_config, "local_num_beams", self.num_beams) or 1),
        )
        self.local_files_only = bool(
            self._get_config_value(
                translator_config,
                "local_files_only",
                self.local_files_only,
            )
        )

        if isinstance(config, dict):
            cli_config = config.get("cli", {})
            self.use_gpu = bool(cli_config.get("use_gpu", True))
        else:
            cli_config = getattr(config, "cli", None)
            self.use_gpu = bool(getattr(cli_config, "use_gpu", True))

    def _resolve_model_source(self) -> str:
        if self.model_path:
            path = str(self.model_path).strip()
            if not os.path.isabs(path):
                path = os.path.join(BASE_PATH, path)
            path = os.path.abspath(path)
            if not os.path.isdir(path):
                raise FileNotFoundError(
                    f"Local NLLB model directory does not exist: {path}"
                )
            return path

        if not self.model_name:
            raise RuntimeError("Local NLLB model name is empty.")
        return self.model_name

    def _resolve_device(self) -> str:
        import torch

        if self.device_preference == "cpu":
            return "cpu"

        if self.device_preference == "cuda":
            if torch.cuda.is_available():
                return "cuda"
            self.logger.warning(
                "Local NLLB requested CUDA but CUDA is unavailable; falling back to CPU."
            )
            return "cpu"

        if self.use_gpu and torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _cache_key(self, model_source: str, device: str) -> str:
        return f"{model_source}::{device}"

    def _load_model_sync(self):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        model_source = self._resolve_model_source()
        device = self._resolve_device()
        cache_key = self._cache_key(model_source, device)

        with self._CACHE_LOCK:
            cached = self._MODEL_CACHE.get(cache_key)
            if cached is not None:
                return cached

            self.logger.info(
                f"Loading Local NLLB model '{model_source}' on {device}. "
                "The first run may download model files; later runs can work offline."
            )

            tokenizer = AutoTokenizer.from_pretrained(
                model_source,
                use_fast=True,
                local_files_only=self.local_files_only,
            )

            dtype = torch.float16 if device == "cuda" else torch.float32
            model = AutoModelForSeq2SeqLM.from_pretrained(
                model_source,
                dtype=dtype,
                low_cpu_mem_usage=True,
                local_files_only=self.local_files_only,
            )
            model.eval()
            model.to(device)

            cached = (tokenizer, model, device)
            self._MODEL_CACHE[cache_key] = cached
            self.logger.info("Local NLLB model loaded successfully.")
            return cached

    @staticmethod
    def _has_japanese_kana(text: str) -> bool:
        return bool(re.search(r"[\u3040-\u30ff\u31f0-\u31ff]", text or ""))

    @staticmethod
    def _has_han(text: str) -> bool:
        return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text or ""))

    @staticmethod
    def _looks_traditional_chinese(text: str) -> bool:
        try:
            import opencc

            simplified = opencc.OpenCC("t2s").convert(text or "")
            return simplified != (text or "")
        except Exception:
            return False

    def _source_hint_code(self) -> str | None:
        value = str(self.source_lang or "auto").strip().upper()
        if value in self._LANGUAGE_CODE_MAP:
            return self._LANGUAGE_CODE_MAP[value]
        return None

    def _detect_source_code(self, text: str) -> str:
        hinted = self._source_hint_code()
        if hinted:
            return hinted

        text = str(text or "").strip()
        if not text:
            return "eng_Latn"

        if self._has_japanese_kana(text):
            return "jpn_Jpan"

        if self._has_han(text):
            detected = ""
            try:
                detected = str(langid.classify(text)[0] or "").lower()
            except Exception:
                detected = ""

            if detected == "ja":
                return "jpn_Jpan"
            if self._looks_traditional_chinese(text):
                return "zho_Hant"
            return "zho_Hans"

        try:
            detected = str(langid.classify(text)[0] or "").lower()
        except Exception:
            detected = ""

        return {
            "ja": "jpn_Jpan",
            "zh": "zho_Hans",
            "en": "eng_Latn",
            "vi": "vie_Latn",
        }.get(detected, "eng_Latn")

    def _translate_group_sync(
        self,
        tokenizer,
        model,
        device: str,
        source_code: str,
        target_code: str,
        texts: List[str],
    ) -> List[str]:
        import torch

        tokenizer.src_lang = source_code
        forced_bos_token_id = tokenizer.convert_tokens_to_ids(target_code)
        if forced_bos_token_id is None or forced_bos_token_id < 0:
            raise RuntimeError(f"Target language token is unavailable: {target_code}")

        results: List[str] = []
        for start in range(0, len(texts), self.batch_size):
            self._check_cancelled()
            chunk = texts[start : start + self.batch_size]
            encoded = tokenizer(
                chunk,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self.max_input_tokens,
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}

            with torch.inference_mode():
                output_ids = model.generate(
                    **encoded,
                    forced_bos_token_id=forced_bos_token_id,
                    max_new_tokens=self.max_new_tokens,
                    num_beams=self.num_beams,
                    early_stopping=self.num_beams > 1,
                )

            decoded = tokenizer.batch_decode(
                output_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            )
            results.extend(text.strip() for text in decoded)

        return results

    def _translate_sync(
        self,
        from_lang: str,
        to_lang: str,
        queries: List[str],
    ) -> List[str]:
        tokenizer, model, device = self._load_model_sync()

        target_code = to_lang
        if target_code == "auto":
            target_code = "vie_Latn"

        grouped: Dict[str, List[tuple[int, str]]] = defaultdict(list)
        if from_lang != "auto":
            for index, query in enumerate(queries):
                grouped[from_lang].append((index, query))
        else:
            for index, query in enumerate(queries):
                grouped[self._detect_source_code(query)].append((index, query))

        translations = [""] * len(queries)
        with self._INFERENCE_LOCK:
            for source_code, items in grouped.items():
                if source_code == target_code:
                    for index, query in items:
                        translations[index] = query
                    continue

                indexes = [index for index, _query in items]
                texts = [query for _index, query in items]
                group_results = self._translate_group_sync(
                    tokenizer,
                    model,
                    device,
                    source_code,
                    target_code,
                    texts,
                )
                for index, translated in zip(indexes, group_results):
                    translations[index] = translated

        return translations

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
        return await asyncio.to_thread(
            self._translate_sync,
            from_lang,
            to_lang,
            list(queries),
        )

    async def unload(self):
        import torch

        with self._CACHE_LOCK:
            entries = list(self._MODEL_CACHE.values())
            self._MODEL_CACHE.clear()

        for _tokenizer, model, device in entries:
            try:
                model.to("cpu")
            except Exception:
                pass
            del model

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        self.logger.info("Local NLLB model cache unloaded.")
