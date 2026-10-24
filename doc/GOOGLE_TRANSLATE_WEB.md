# Google Translate Web backend

`google_web` automates the public Google Translate website through Playwright.
It does not require a Gemini/OpenAI/Google Cloud API key.

## Requirements

- Internet connection.
- Python package `playwright`.
- Microsoft Edge or Google Chrome installed locally. On Windows, Edge is tried first.

Because Playwright can drive installed Edge/Chrome channels, a normal Windows
setup does not need a separate Chromium download.

## Recommended settings for English manga

- Translator: `google_web`
- Target Language: `VIN`
- Keep Source Language: `none`
- Google Web Source Language: `ENG`
- Google Web Browser: `auto`
- Google Web Headless: `true`
- Google Web Delay: `900 ms`
- Google Web Timeout: `20000 ms`
- Google Web Retries: `2`

Use `JPN`, `CHS`, or `CHT` for Japanese, Simplified Chinese, or Traditional
Chinese chapters. `auto` is available but an explicit source language is more
reliable for very short manga dialogue and sound effects.

## Reliability

This backend is website automation rather than an official translation API.
Google may change the page DOM, consent flow, or rate limiting. The translator
therefore keeps selectors centralized, retries transient failures, serializes
requests, and caches duplicate strings for the current application session.
