# White-label Reges

Everything a reseller needs to change lives in three files. No code edits.

## 1. Name and wording

`reges/brand.py` (create it — every string below has a default in code):

```python
BRAND = {
    "name":     "REGES",
    "mark":     "R·E·G·E·S",          # spaced brand mark in the header
    "tagline":  "Something is about to wake up.",
    "company":  "Like A King Inc.",
    "support":  "https://your-site.com/support",
    "docs":     "https://your-site.com/docs",
}
```

## 2. Look

`hud/themes.js` — add an entry and it appears everywhere: setup wizard swatches,
settings, the live HUD, the animated background.

```js
yourbrand: {
  name: 'Your Brand', tag: 'however you describe it',
  bg: '#07060a', ink: '#e8dcc4', accent: '#c9a84c',
  glow: ['#3a2c0c', '#150f04'], grain: 0.05,
  colors: { idle: '…', listening: '…', thinking: '…', reasoning: '…',
            working: '…', speaking: '…', error: '…' },
}
```

Orb bodies live in `hud/orb.js` under `ORB_VARIANTS`. Six ship; adding a
seventh is a geometry branch in `_build()` and an optional deformation in the
draw loop.

## 3. Models offered

`reges/models_catalog.py` — one `Model` entry with real filenames and sizes.
The wizard reads VRAM, matches a quant, and downloads it. Nothing else to wire.

Rule that keeps this honest: **if a file is not in the catalog, Reges will not
offer to download it.** Check the repo listing before adding entries — sizes
drive the recommendation.

## Packaging for sale

- Ship the folder as-is. `START.bat` is the entry point.
- First launch opens the wizard; after Deploy it opens the console.
- `setup_complete = false` in config.toml re-runs the wizard, so a support
  answer for "start over" is one line.
- Nothing phones home. No telemetry exists in this codebase — if you want it,
  you have to add it, and you should say so in your own terms.
- Secrets live in the OS credential store, never in config.toml, so a config
  file is safe to email to a customer for debugging.

## What buyers will ask first

1. **"Do I need a graphics card?"** No. The wizard's API path needs nothing but
   a key. Local models need one.
2. **"How much does it cost to run?"** Local: electricity. API: the footer
   shows real spend, and local tokens are explicitly marked free.
3. **"Where is my data?"** The vault folder they chose in step 3. Plain
   markdown. No database, no cloud.
