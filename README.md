# Keep-Import

**Evernote → Google Keep importer**

A practical, resumable Python tool for migrating notes from Evernote (`.enex` export) into Google Keep after Bending Spoons raised prices and changed the subscription tiers.

## Why this exists

In 2026 Bending Spoons (the company that acquired Evernote) discontinued the old Personal/Professional plans and introduced new tiers. The only practical option for anyone with a real archive of notes was the **Advanced** plan at **$249.99/year**.

I refused to pay that.

Evernote’s export produces a usable `.enex` file, but Google Keep has no official bulk import path. Manual migration is fine for a few dozen notes and completely impractical for thousands. So I wrote a small, focused importer that does the job reliably.

This is not a general-purpose Evernote conversion suite. It is a targeted escape hatch written by a long-time systems engineer who wanted his data back under his own control.

## What it does

- Streams large `.enex` files with low memory use (`xml.etree.ElementTree.iterparse`)
- Converts Evernote ENML content into clean, readable plain text
- Maps Evernote tags → Google Keep labels (creating labels as needed)
- Extracts attachments to a local directory and records the paths inside each Keep note
- Splits notes that exceed Keep’s practical length limits
- Tracks progress in a cache file so you can interrupt (Ctrl+C) and safely resume
- Supports dry-run mode and limited test runs (`--limit N`)
- Authenticates with Google Keep using a master token (the only method that works with current `gkeepapi`)

## Requirements

- Python 3.10+
- Packages listed in `requirements.txt` (mainly `gkeepapi`, `beautifulsoup4`, `lxml`, `gpsoauth`)

## Quick start

```bash
# Clone and set up
git clone https://github.com/jasontromm/Keep-Import.git
cd Keep-Import
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# One-time authentication setup
.venv/bin/python3 import_evernote_to_keep.py --setup-token

# Test with a few notes
.venv/bin/python3 import_evernote_to_keep.py --limit 5

# Full import (safe to interrupt and resume)
.venv/bin/python3 import_evernote_to_keep.py
```

See **[import_instructions.md](import_instructions.md)** for the complete setup guide, all command-line options, and security notes about the master token.

## Design notes

- **Memory first** — never load the entire ENEX into RAM
- **Resume capability** — progress is written to `.imported_notes_cache.json`
- **Graceful degradation** — attachments are extracted even though `gkeepapi` cannot currently upload images into Keep notes
- **No happy-path assumptions** — long notes are split, authentication is documented carefully, and the tool can be stopped cleanly

## Limitations

- Image/file upload into Keep notes is not supported by the current `gkeepapi`. Attachments are saved locally and referenced in the note text.
- Complex nested formatting is flattened into readable plain text.
- Google authentication surfaces change; the master-token method is the working path as of August 2026.

## License

Use freely. No warranty. This is a personal migration tool shared so others in the same situation have a starting point.

---

**Disclaimer**  
The code in this repository was written with assistance from Grok (xAI). The design decisions, testing, and final responsibility for the tool remain with the author.
