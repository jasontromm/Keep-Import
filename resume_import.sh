#!/usr/bin/env bash
# Resume Evernote → Google Keep import from where it left off.
# Progress is tracked in .imported_notes_cache.json; already-imported
# notes are skipped automatically.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python3"
IMPORTER="${ROOT}/import_evernote_to_keep.py"
TOKEN_FILE="${ROOT}/.keep_token"
CACHE_FILE="${ROOT}/.imported_notes_cache.json"
ENEX="${ROOT}/Evernote Notebook.enex"

usage() {
  cat <<'EOF'
Usage: ./resume_import.sh [options] [-- importer-args...]

Resume the Evernote → Google Keep import. Notes already in the
resume cache are skipped.

Convenience options (handled by this script):
  -h, --help          Show this help
  -n, --limit N       Only process N more notes (passes --limit N)
  -d, --dry-run       Dry-run only (no Google Keep calls)
  -s, --setup-token   Run master-token setup wizard, then exit
  -t, --test          Import 5 notes (quick smoke test)
  --skip-initial-sync Faster login if Keep already has many notes

Any other args are passed through to import_evernote_to_keep.py.

Examples:
  ./resume_import.sh
  ./resume_import.sh --test
  ./resume_import.sh --limit 50
  ./resume_import.sh --dry-run
  ./resume_import.sh --setup-token
  ./resume_import.sh -- --batch-size 25 --skip-initial-sync
EOF
}

LIMIT=""
DRY_RUN=0
SETUP_TOKEN=0
SKIP_SYNC=0
PASSTHRU=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    -n|--limit)
      LIMIT="${2:?--limit requires a number}"
      shift 2
      ;;
    -d|--dry-run)
      DRY_RUN=1
      shift
      ;;
    -s|--setup-token)
      SETUP_TOKEN=1
      shift
      ;;
    -t|--test)
      LIMIT=5
      shift
      ;;
    --skip-initial-sync)
      SKIP_SYNC=1
      shift
      ;;
    --)
      shift
      PASSTHRU+=("$@")
      break
      ;;
    *)
      PASSTHRU+=("$1")
      shift
      ;;
  esac
done

if [[ ! -x "$PYTHON" ]]; then
  echo "Error: venv python not found at $PYTHON" >&2
  echo "Create it with: python3 -m venv .venv && .venv/bin/pip install gkeepapi beautifulsoup4 lxml" >&2
  exit 1
fi

if [[ ! -f "$IMPORTER" ]]; then
  echo "Error: importer not found at $IMPORTER" >&2
  exit 1
fi

if [[ "$SETUP_TOKEN" -eq 1 ]]; then
  exec "$PYTHON" "$IMPORTER" --setup-token --token-file "$TOKEN_FILE"
fi

if [[ "$DRY_RUN" -eq 0 && ! -f "$TOKEN_FILE" ]]; then
  echo "No master token file at: $TOKEN_FILE" >&2
  echo "Set one up first:" >&2
  echo "  $0 --setup-token" >&2
  echo "See import_instructions.md for Edge/browser steps." >&2
  exit 1
fi

if [[ ! -f "$ENEX" ]]; then
  echo "Warning: default ENEX not found at: $ENEX" >&2
  echo "Pass --enex /path/to/file.enex after -- if needed." >&2
fi

if [[ -f "$CACHE_FILE" ]]; then
  CACHED="$("$PYTHON" -c "import json; print(len(json.load(open('$CACHE_FILE'))))" 2>/dev/null || echo "?")"
  echo "Resume cache: $CACHED note(s) already imported ($CACHE_FILE)"
else
  echo "Resume cache: none yet (fresh start)"
fi

echo "Starting import from: $ROOT"
echo "Press Ctrl+C anytime; re-run this script to continue."
echo

ARGS=(
  --enex "$ENEX"
  --token-file "$TOKEN_FILE"
  --cache-file "$CACHE_FILE"
)

if [[ -n "$LIMIT" ]]; then
  ARGS+=(--limit "$LIMIT")
fi
if [[ "$DRY_RUN" -eq 1 ]]; then
  ARGS+=(--dry-run)
fi
if [[ "$SKIP_SYNC" -eq 1 ]]; then
  ARGS+=(--skip-initial-sync)
fi

exec "$PYTHON" "$IMPORTER" "${ARGS[@]}" "${PASSTHRU[@]}"
