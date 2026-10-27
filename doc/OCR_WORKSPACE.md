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
translation per line and maps those lines in region order.

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

For a fast local scan, use a local OCR backend such as `mocr` or the existing
48px OCR instead of an API OCR. Detection/OCR settings continue to come from the
normal Settings page so OCR Workspace does not maintain a second incompatible
configuration.
