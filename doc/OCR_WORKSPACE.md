# OCR Workspace

OCR Workspace is a separate manual-translation workflow optimized for speed.

## Scan pipeline

```
Raw manga
-> Detection
-> OCR
-> Text-line merge
-> Project JSON
```

The scan deliberately skips translation, colorization, upscaling, mask refinement,
inpainting, typesetting, and final image rendering.

**Existing project JSON is never overwritten by OCR-only scan.** If OCR
results already exist for a page, the page is left untouched so translations
and manual edits are safe. To genuinely re-scan a page, move or rename that
page's existing `manga_translator_work/json/*_translations.json` file first
(keep it as a backup).

## Two-pane workflow

- Left: region number, editable OCR text, editable translation.
- Right: original raw page.
- Selecting a row highlights its saved region on the raw image.

## External translation

**Copy All OCR** copies the current page with stable markers:

```text
[001] 起きてきたの？体、大丈夫？
[002] マッサージして…
```

Translate the block in an external tool while preserving the markers, copy the
translated block, then press **Paste Batch**. Marker IDs map translations back to
the original MangaEditor regions.

If the external tool removes markers, Paste Batch also accepts one non-empty
translation per line and maps those lines in region order, **but only if the
line count matches the number of regions exactly**. Invalid region markers
are rejected to prevent dialogue from being assigned to the wrong bubble.

## Saving

**Save JSON** updates the existing MangaEditor project JSON. A
`.ocr_workspace.bak` backup is written before replacement. The workspace writes
translation text only and removes stale rich-text data for a region when its
plain translation changes.

## Batch export

- **Export Batch TXT** exports OCR + current translations for all pages in the
  workspace.
- **Render Batch** reads the edited project JSON directly, skips OCR and
  translation, then runs only the necessary inpainting/typesetting/export
  stages. Old TXT sidecars are intentionally ignored so they cannot overwrite
  workspace edits.

## Speed recommendations

For a fast local scan, choose a local OCR backend such as `mocr`, `48px`, or
PaddleOCR in **Settings → OCR**. OCR Workspace blocks OpenAI/Gemini OCR (including
hybrid secondary OCR) to prevent unwanted API calls. Detection/OCR settings
continue to come from the normal Settings page so OCR Workspace does not
maintain a second incompatible configuration.

## Update source checkout

```powershell
cd D:\\app\\MangaEditorV1
git fetch https://github.com/ThanTuan399/MangaEditor.git NewMangaEditor
git switch NewMangaEditor
git merge --ff-only FETCH_HEAD
.\\Win-Start.bat
```

If this checkout is on another branch and has uncommitted changes, back
them up before switching. Do not use a force reset.
