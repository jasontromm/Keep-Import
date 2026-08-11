# Evernote → Google Keep Import Instructions

## Prerequisites

You need **Python 3**, a **project virtual environment**, and the packages in
`requirements.txt` (including **gkeepapi**). Work from the project directory:

```bash
cd ~/Projects/Keep
```

### 1. Check Python 3

```bash
python3 --version
```

You want Python **3.10+** (3.12 is fine). If the command is missing, install
Python 3 for your OS (for example on Ubuntu/Debian):

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

Also confirm `venv` is available:

```bash
python3 -m venv --help >/dev/null && echo "venv OK"
```

### 2. Create a virtual environment

If `.venv` does not already exist:

```bash
python3 -m venv .venv
```

Activate it (optional when you call `.venv/bin/python3` directly):

```bash
source .venv/bin/activate
```

Upgrade packaging tools inside the venv:

```bash
.venv/bin/python3 -m pip install --upgrade pip setuptools wheel
```

### 3. Install gkeepapi and other dependencies

Preferred (pinned versions from this repo):

```bash
.venv/bin/pip install -r requirements.txt
```

That installs **gkeepapi**, **gpsoauth**, **beautifulsoup4**, **lxml**, and
**requests**.

Minimal install only (if you are not using `requirements.txt`):

```bash
.venv/bin/pip install gkeepapi beautifulsoup4 lxml
```

### 4. Verify the install

```bash
.venv/bin/python3 -c "import gkeepapi; print('gkeepapi', getattr(gkeepapi, '__version__', 'unknown'))"
.venv/bin/python3 -c "from bs4 import BeautifulSoup; import lxml; print('bs4 + lxml OK')"
.venv/bin/python3 test_gkeepapi.py
```

You should see a gkeepapi version (this project targets **0.17.x**) and
successful Keep object initialization. If imports fail, re-run the `pip install`
step and confirm you are using `.venv/bin/python3` / `.venv/bin/pip`, not system
Python.

### Quick re-check later

```bash
test -x .venv/bin/python3 && echo "venv present"
.venv/bin/python3 -c "import gkeepapi, bs4, lxml; print('deps OK')"
```

After prerequisites are in place, continue with the master-token setup below.

## One-time setup: get a master token

1. Open a private/incognito browser window.
2. Go to: <https://accounts.google.com/EmbeddedSetup>
3. Sign in to the Google account you want to use for Keep.
4. Click **I agree** if prompted. The page may spin forever — that is OK.
5. Open DevTools (`F12`)
   - **Application** (Chrome) or **Storage** (Firefox)
   - **Cookies** → `https://accounts.google.com`
6. Copy the value of the cookie named: `oauth_token`  
   (it usually starts with `oauth2_4/`)
7. From this project directory, run:

   ```bash
   cd ~/Projects/Keep
   .venv/bin/python3 import_evernote_to_keep.py --setup-token
   ```

8. Paste your Google email and the `oauth_token` cookie when prompted.

The script exchanges the cookie for a master token and saves it to:

```text
~/Projects/Keep/.keep_token
```

**Security:** the master token has full access to your Google account. Treat it like a password. Do not commit `.keep_token` to git (it is listed in `.gitignore`).

## Import your Evernote notebook

Test a few notes first:

```bash
.venv/bin/python3 import_evernote_to_keep.py --limit 5
```

Full import (safe to interrupt with Ctrl+C; progress is cached):

```bash
.venv/bin/python3 import_evernote_to_keep.py
```

Dry-run only (parse ENEX, extract attachments, no Google API):

```bash
.venv/bin/python3 import_evernote_to_keep.py --dry-run
```

Dry-run with a small sample:

```bash
.venv/bin/python3 import_evernote_to_keep.py --dry-run --limit 10
```

## Useful options

| Option | Description |
|--------|-------------|
| `--enex PATH` | Path to the `.enex` file (default: `Evernote Notebook.enex`) |
| `--email EMAIL` | Google account email |
| `--master-token TOKEN` | Master token on the command line (prefer `.keep_token` instead) |
| `--token-file PATH` | Where to read/write credentials (default: `.keep_token`) |
| `--setup-token` | Wizard to obtain and save a master token |
| `--limit N` | Stop after N notes (good for testing) |
| `--batch-size N` | Sync to Keep every N notes (default: 50) |
| `--chunk-limit N` | Split long notes at N chars (default: 18000) |
| `--dry-run` | No Google Keep calls |
| `--no-cache` | Re-import even if already in resume cache |
| `--skip-initial-sync` | Faster login if you already have many Keep notes |
| `--upload-images` | Not supported by gkeepapi; attachments are only saved under `extracted_attachments/` |

## Environment variables (optional)

- `GOOGLE_EMAIL` or `KEEP_EMAIL`
- `GOOGLE_MASTER_TOKEN` or `KEEP_MASTER_TOKEN`

## Resume / progress

Successfully imported notes are recorded in:

```text
.imported_notes_cache.json
```

Re-running the script skips notes already in that cache. If something fails mid-run, just run the same command again.

## Attachments

Images and other files from Evernote are extracted to:

```text
extracted_attachments/
```

Each Keep note text includes a `Local Attachments:` list of those paths. gkeepapi cannot upload images into Keep notes.

## If auth fails again

Your master token is missing, expired, or invalid. Re-run:

```bash
.venv/bin/python3 import_evernote_to_keep.py --setup-token
```

Use a fresh `oauth_token` cookie from a private browser session.
