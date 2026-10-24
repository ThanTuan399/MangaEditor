# Google Translate Image/Lens-style backend

`google_image_web` uses Google Translate's **Images** web mode for each
MangaEditor text region. It does not use a Google Cloud, Gemini, or OpenAI API
key.

Google's desktop Translate UI supports uploading JPG/JPEG/PNG/WebP images and,
after translation, provides a **Copy text** action for the translated text.
MangaEditor uses that flow through Playwright.

## Pipeline

1. MangaEditor detects and merges a text region.
2. The region is cropped from the original page with configurable padding.
3. Small crops are upscaled before upload to improve Google's image OCR.
4. Playwright uploads the crop to Google Translate Images.
5. MangaEditor clicks **Copy text** and reads the translated text.
6. The result is mapped back to the same region for normal inpainting and
   typesetting.
7. If image translation fails and fallback is enabled, the region is sent
   through the existing Google Translate text automation backend.

This is intentionally region-based rather than whole-page image translation:
MangaEditor must preserve each region's coordinates so the translated string can
be placed back into the correct speech bubble.

## Recommended settings

For English manga:

- Translator: `Google Translate (Image/Lens)`
- Target Language: `Vietnamese`
- Keep Source Language: `No Filter`
- Google Source Language: `English`
- Google Browser: `Auto (Edge preferred)`
- Google Browser Headless: `Off` for the first test, then `On`
- Google Image Crop Padding: `0.45`
- Google Image Minimum Side: `512`
- Google Image Fallback to Text: `On`
- Google Request Delay: `900 ms`
- Google Timeout: `20000 ms`
- Google Retries: `2`

For Japanese/Chinese, change only Google Source Language.

## Important limitations

This backend automates a public website, not an official API. Google can change
the page UI or rate limits. The app therefore keeps browser selectors isolated,
uses retries, and falls back to text translation when enabled.

This mode uses Google Translate Images. It is Lens-style image translation, but
it does not claim to be the separate Google Lens product or to expose Google's
internal OCR/translation model.
