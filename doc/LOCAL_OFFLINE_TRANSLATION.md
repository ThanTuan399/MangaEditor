# Local Offline Translation (NewMangaEditor)

This branch adds the first API-independent translation backend: `local_nllb`.

## Goal

The normal manga pipeline remains unchanged:

```
Detection -> OCR -> Local Translation -> Inpainting -> Typesetting -> Editor/Export
```

Translation can run without Gemini/OpenAI/API keys. Internet is only needed the
first time if the selected model is not already present in the local Hugging Face
cache.

## Supported source languages

- Japanese: `JPN / jpn_Jpan`
- Simplified Chinese: `CHS / zho_Hans`
- Traditional Chinese: `CHT / zho_Hant`
- English: `ENG / eng_Latn`

Target Vietnamese uses `VIN / vie_Latn`.

## Default model

`facebook/nllb-200-distilled-600M`

The model is separate from this repository. Review the model license before
redistributing or using it commercially.

## Settings

Select:

- Translator: `local_nllb`
- Target Language: `VIN`
- Local Source Lang: `auto`, `JPN`, `CHS`, `CHT`, or `ENG`
- Local Device: `auto`, `cuda`, or `cpu`

For manga that contains only Han characters and could be Japanese or Chinese,
choose an explicit source language for the most reliable result.

Set `local_model_path` to an already downloaded model directory and enable
`local_files_only` to guarantee that translation never attempts a network
download.

## Next steps

1. Add a model manager/download UI with disk-size and license information.
2. Add Translation Memory and glossary/rule post-processing.
3. Add a CTranslate2 optimized backend for lower VRAM usage and faster inference.
4. Integrate enhanced local typesetting/editor capabilities.
