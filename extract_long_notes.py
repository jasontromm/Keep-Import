#!/usr/bin/env python3
"""
Extract Evernote notes whose plain-text body exceeds a character threshold.

Writes one Google-Docs-friendly text file per matching note, plus an index.
Default threshold: 1000 characters.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Reuse ENML → plain text conversion from the importer
from import_evernote_to_keep import convert_enml_to_plain_text, format_timestamp, sanitize_name

_PROJECT_DIR = os.path.join(os.path.expanduser("~"), "Projects", "Keep")


def parse_args():
    p = argparse.ArgumentParser(
        description="Extract ENEX notes longer than N plain-text characters."
    )
    p.add_argument(
        "--enex",
        default=os.path.join(_PROJECT_DIR, "Evernote Notebook.enex"),
        help="Path to the .enex export",
    )
    p.add_argument(
        "--min-chars",
        type=int,
        default=1000,
        help="Minimum plain-text character count (default: 1000)",
    )
    p.add_argument(
        "--out-dir",
        default=os.path.join(_PROJECT_DIR, "long_notes_for_docs"),
        help="Directory for extracted note files",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after scanning this many notes (testing)",
    )
    p.add_argument(
        "--format",
        choices=("txt", "md", "both"),
        default="txt",
        help="Output format for each note (default: txt)",
    )
    return p.parse_args()


def unique_filename(out_dir: str, base: str, ext: str, used: set[str]) -> str:
    """Return a unique filename stem under out_dir."""
    stem = base or "untitled"
    candidate = f"{stem}.{ext}"
    n = 2
    while candidate in used or os.path.exists(os.path.join(out_dir, candidate)):
        candidate = f"{stem}_{n}.{ext}"
        n += 1
    used.add(candidate)
    return candidate


def write_note_file(
    path: str,
    *,
    title: str,
    created: str,
    updated: str,
    tags: list[str],
    body: str,
    as_markdown: bool,
) -> None:
    lines: list[str] = []
    if as_markdown:
        lines.append(f"# {title or 'Untitled'}")
        lines.append("")
        if created:
            lines.append(f"- **Created:** {format_timestamp(created)}")
        if updated:
            lines.append(f"- **Updated:** {format_timestamp(updated)}")
        if tags:
            lines.append(f"- **Tags:** {', '.join(tags)}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(body)
        lines.append("")
    else:
        lines.append(title or "Untitled")
        lines.append("=" * max(len(title or "Untitled"), 10))
        lines.append("")
        if created:
            lines.append(f"Created: {format_timestamp(created)}")
        if updated:
            lines.append(f"Updated: {format_timestamp(updated)}")
        if tags:
            lines.append(f"Tags:    {', '.join(tags)}")
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
        lines.append(body)
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    args = parse_args()
    enex_path = args.enex
    out_dir = args.out_dir
    min_chars = args.min_chars

    if not os.path.isfile(enex_path):
        print(f"Error: ENEX not found: {enex_path}", file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    used_names: set[str] = set()
    index_rows: list[dict] = []

    scanned = 0
    matched = 0
    skipped_empty = 0
    errors = 0

    print(f"ENEX:       {enex_path}")
    print(f"Threshold:  > {min_chars} plain-text characters")
    print(f"Output dir: {out_dir}")
    print(f"Format:     {args.format}")
    print("Scanning (this can take a while for large exports)...")
    print()

    try:
        context = ET.iterparse(enex_path, events=("end",))
        for _event, elem in context:
            if elem.tag != "note":
                continue

            scanned += 1
            try:
                title = (elem.findtext("title") or "").strip() or "Untitled"
                created = elem.findtext("created") or ""
                updated = elem.findtext("updated") or ""
                tags = [t.text for t in elem.findall("tag") if t.text]
                content_xml = elem.findtext("content") or ""

                body = convert_enml_to_plain_text(content_xml)
                char_count = len(body)

                if char_count == 0:
                    skipped_empty += 1
                elif char_count > min_chars:
                    matched += 1
                    # Filename from title only (no leading sequence number)
                    base = sanitize_name(title)[:80] or "Untitled"

                    files_written = []
                    if args.format in ("txt", "both"):
                        name = unique_filename(out_dir, base, "txt", used_names)
                        path = os.path.join(out_dir, name)
                        write_note_file(
                            path,
                            title=title,
                            created=created,
                            updated=updated,
                            tags=tags,
                            body=body,
                            as_markdown=False,
                        )
                        files_written.append(name)

                    if args.format in ("md", "both"):
                        name = unique_filename(out_dir, base, "md", used_names)
                        path = os.path.join(out_dir, name)
                        write_note_file(
                            path,
                            title=title,
                            created=created,
                            updated=updated,
                            tags=tags,
                            body=body,
                            as_markdown=True,
                        )
                        files_written.append(name)

                    index_rows.append(
                        {
                            "index": matched,
                            "title": title,
                            "chars": char_count,
                            "created": format_timestamp(created),
                            "updated": format_timestamp(updated),
                            "tags": "; ".join(tags),
                            "files": "; ".join(files_written),
                        }
                    )

                    if matched <= 5 or matched % 50 == 0:
                        print(
                            f"  [{matched}] {char_count:>6} chars  {title[:70]!r}"
                        )

            except Exception as e:
                errors += 1
                print(f"  Warning: failed on note #{scanned}: {e}", file=sys.stderr)
            finally:
                elem.clear()

            if args.limit and scanned >= args.limit:
                print(f"\nReached --limit {args.limit}; stopping scan.")
                break

    except Exception as e:
        print(f"Fatal parse error after {scanned} notes: {e}", file=sys.stderr)
        return 1

    # Write index files
    index_csv = os.path.join(out_dir, "INDEX.csv")
    index_json = os.path.join(out_dir, "INDEX.json")
    index_md = os.path.join(out_dir, "INDEX.md")

    fieldnames = ["index", "title", "chars", "created", "updated", "tags", "files"]
    with open(index_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(index_rows)

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "enex": enex_path,
        "min_chars": min_chars,
        "scanned": scanned,
        "matched": matched,
        "skipped_empty": skipped_empty,
        "errors": errors,
        "notes": index_rows,
    }
    with open(index_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    with open(index_md, "w", encoding="utf-8") as f:
        f.write("# Long notes for Google Docs\n\n")
        f.write(f"- **Threshold:** > {min_chars} characters (plain text)\n")
        f.write(f"- **Scanned:** {scanned}\n")
        f.write(f"- **Matched:** {matched}\n")
        f.write(f"- **Generated:** {summary['generated_at']}\n\n")
        f.write("| # | Chars | Title | File(s) |\n")
        f.write("|---|------:|-------|--------|\n")
        for row in index_rows:
            title_esc = row["title"].replace("|", "\\|")
            f.write(
                f"| {row['index']} | {row['chars']} | {title_esc} | `{row['files']}` |\n"
            )

    print()
    print("Done.")
    print(f"  Scanned:  {scanned}")
    print(f"  Matched:  {matched} (>{min_chars} chars)")
    print(f"  Empty:    {skipped_empty}")
    print(f"  Errors:   {errors}")
    print(f"  Index:    {index_csv}")
    print(f"  Notes in: {out_dir}")
    print()
    print("To import into Google Docs:")
    print("  1. Open Google Drive → New → File upload (or drag the folder)")
    print("  2. Upload the .txt files from the output directory")
    print("  3. Open a file with Google Docs (right-click → Open with → Google Docs)")
    print("  Or bulk-upload via Drive; Docs converts plain text cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
