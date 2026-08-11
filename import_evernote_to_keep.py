#!/usr/bin/env python3
"""
Evernote to Google Keep Import Tool
Author: Jason A. Trommetter (with assistance from Grok)
Date: August 2026

A robust, memory-efficient utility to parse massive Evernote (.enex) files 
and import them into Google Keep using the gkeepapi library.
"""

import os
import sys
import re
import json
import hashlib
import argparse
import base64
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

# Default project paths under $HOME (portable across machines/usernames)
_PROJECT_DIR = os.path.join(os.path.expanduser("~"), "Projects", "Keep")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Memory-efficient importer from Evernote (.enex) to Google Keep.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        epilog=(
            "Authentication: gkeepapi no longer accepts Google passwords. "
            "You need a master token (see --setup-token)."
        ),
    )
    parser.add_argument(
        "--enex",
        type=str,
        default=os.path.join(_PROJECT_DIR, "Evernote Notebook.enex"),
        help="Path to the Evernote Notebook.enex file"
    )
    parser.add_argument(
        "--email",
        type=str,
        help="Google Account Email address (will prompt if not provided)"
    )
    parser.add_argument(
        "--master-token",
        type=str,
        help="Google master token (aas_et/... or oauth2rt_1/...). Prefer --token-file for security."
    )
    parser.add_argument(
        "--token-file",
        type=str,
        default=os.path.join(_PROJECT_DIR, ".keep_token"),
        help="Path to cache/read email + master token (JSON or plain token text)"
    )
    parser.add_argument(
        "--setup-token",
        action="store_true",
        help="Interactive wizard to obtain and save a master token, then exit"
    )
    parser.add_argument(
        "--cache-file",
        type=str,
        default=os.path.join(_PROJECT_DIR, ".imported_notes_cache.json"),
        help="Path to track which notes have already been successfully imported"
    )
    parser.add_argument(
        "--attachments-dir",
        type=str,
        default=os.path.join(_PROJECT_DIR, "extracted_attachments"),
        help="Directory to save extracted note attachments"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of notes to import and sync as a single batch"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after processing this many notes (useful for testing)"
    )
    parser.add_argument(
        "--chunk-limit",
        type=int,
        default=18000,
        help="Character limit per Google Keep note (will split longer notes)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the ENEX file and simulate the import without calling Google Keep"
    )
    parser.add_argument(
        "--upload-images",
        action="store_true",
        help="(Not supported by gkeepapi) Kept for compatibility; images are only saved locally"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable resume cache and re-process all notes"
    )
    parser.add_argument(
        "--skip-initial-sync",
        action="store_true",
        help="Skip downloading existing Keep notes on login (faster; labels may be incomplete until first batch sync)"
    )
    return parser.parse_args()


def print_token_setup_instructions():
    """Print how to obtain a Google master token for gkeepapi."""
    print(
        """
================================================================
 How to get a Google Keep master token (required)
================================================================
gkeepapi 0.17+ cannot log in with a normal password or App Password.
Google blocks that path (BadAuthentication / NeedsBrowser).

Use the browser OAuth-cookie exchange instead:

  1. Open a private/incognito browser window.
  2. Go to:  https://accounts.google.com/EmbeddedSetup
  3. Sign in to the Google account you want to use for Keep.
  4. Click "I agree" if prompted. The page may spin forever — that is OK.
  5. Open DevTools (F12) → Application (Chrome) or Storage (Firefox)
     → Cookies → https://accounts.google.com
  6. Copy the value of the cookie named:  oauth_token
     (it usually starts with "oauth2_4/")
  7. Run:

       .venv/bin/python3 import_evernote_to_keep.py --setup-token

     and paste your email, the oauth_token cookie, and press Enter.
     The script will exchange it for a master token and save it to
     .keep_token for future runs.

Security: the master token has full access to your Google account.
Treat it like a password. Do not commit .keep_token to git.
================================================================
"""
    )


def load_token_file(token_path):
    """
    Load credentials from token file.
    Supports:
      - JSON: {"email": "...", "master_token": "..."}
      - Plain text: just the master token string
    Returns (email_or_None, master_token_or_None).
    """
    if not os.path.exists(token_path):
        return None, None
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if not raw:
            return None, None
        if raw.startswith("{"):
            data = json.loads(raw)
            return data.get("email"), data.get("master_token") or data.get("token")
        # Plain token file
        return None, raw
    except Exception as e:
        print(f"Warning: Could not read token file '{token_path}': {e}")
        return None, None


def save_token_file(token_path, email, master_token):
    """Persist email + master token as JSON with restricted permissions."""
    payload = {"email": email, "master_token": master_token}
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    try:
        os.chmod(token_path, 0o600)
    except OSError:
        pass


def setup_master_token(email=None, token_path=None):
    """
    Interactive wizard: exchange an oauth_token browser cookie for a master token
    via gpsoauth.exchange_token, then save it.
    """
    import gpsoauth
    from uuid import getnode as get_mac

    print_token_setup_instructions()
    print("=== Master token setup ===\n")

    if not email:
        email = input("Google account email: ").strip()
    if not email:
        print("Email is required.")
        sys.exit(1)

    oauth_token = input("Paste oauth_token cookie value: ").strip()
    if not oauth_token:
        print("oauth_token is required.")
        sys.exit(1)

    # Stable device id (hex MAC), same scheme gkeepapi uses by default
    android_id = f"{get_mac():x}"
    print(f"\nExchanging token (android_id={android_id})...")

    try:
        response = gpsoauth.exchange_token(email, oauth_token, android_id)
    except Exception as e:
        print(f"Token exchange request failed: {e}")
        sys.exit(1)

    master_token = response.get("Token")
    if not master_token:
        print("Token exchange failed. Full response:")
        print(json.dumps(response, indent=2, default=str))
        print("\nCommon causes: expired oauth_token cookie, wrong email, or cookie already used.")
        sys.exit(1)

    if token_path:
        save_token_file(token_path, email, master_token)
        print(f"\nMaster token saved to: {token_path}")
    print("Master token (first 24 chars):", master_token[:24] + "...")
    print("\nYou can now run the importer without --setup-token.")
    return email, master_token


def authenticate_keep(email, master_token, skip_initial_sync=False):
    """
    Authenticate to Google Keep using a master token.
    Returns a connected gkeepapi.Keep instance.
    """
    import gkeepapi

    keep = gkeepapi.Keep()
    print("Authenticating with Google Keep (master token)...")
    try:
        # authenticate() is the supported path in gkeepapi 0.17+
        keep.authenticate(email, master_token, sync=not skip_initial_sync)
    except gkeepapi.exception.LoginException as e:
        print(f"\nFailed to authenticate: {e}")
        print("\nYour master token is missing, expired, or invalid.")
        print_token_setup_instructions()
        print("Re-run with:  .venv/bin/python3 import_evernote_to_keep.py --setup-token")
        sys.exit(1)
    except Exception as e:
        print(f"\nFailed to authenticate: {e}")
        print_token_setup_instructions()
        sys.exit(1)

    print("Successfully authenticated with Google Keep.")
    return keep


def sanitize_name(name):
    """Sanitizes names for folders and files to avoid path injection or OS limitations."""
    if not name:
        return "unnamed"
    # Replace invalid chars with underscores
    sanitized = re.sub(r'[\\/*?:"<>| ]', '_', name)
    # Collapse multiple underscores and trim
    sanitized = re.sub(r'_+', '_', sanitized).strip('_')
    return sanitized or "unnamed"


def get_note_fingerprint(title, created):
    """Generates a unique SHA-256 fingerprint for a note based on its title and creation time."""
    key = f"{title or ''}||{created or ''}"
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def format_timestamp(ts_str):
    """Converts Evernote timestamp YYYYMMDDTHHMMSSZ to human readable UTC format."""
    if not ts_str:
        return "Unknown"
    try:
        dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%SZ")
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except ValueError:
        return ts_str


def convert_enml_to_plain_text(content_xml):
    """
    Parses ENML (Evernote XML) and converts it into beautifully formatted plain text.
    Handles headings, blockquotes, lists, checklists, tables, and links.
    """
    if not content_xml or not content_xml.strip():
        return ""
    
    try:
        # Parse ENML as HTML using lxml's parser
        soup = BeautifulSoup(content_xml, "lxml")
        
        # 1. Translate Evernote checkboxes (<en-todo>) to clean plain-text indicators
        for todo in soup.find_all('en-todo'):
            checked = todo.get('checked') == 'true'
            checkbox_str = "[x] " if checked else "[ ] "
            todo.replace_with(checkbox_str)
            
        # 2. Translate media tags (<en-media>) to inline descriptions
        for media in soup.find_all('en-media'):
            mime = media.get('type', '')
            placeholder = f" [Attachment: {mime or 'file'}] "
            media.replace_with(placeholder)
            
        # 3. Format hyperlinks cleanly
        for a in soup.find_all('a'):
            href = a.get('href')
            text = a.get_text().strip()
            if href:
                if text and text != href:
                    a.replace_with(f"{text} ({href})")
                else:
                    a.replace_with(href)
                    
        # 4. Recursive structure renderer
        def render_element(element):
            if element.name is None:  # NavigableString
                return element.string or ""
                
            tag = element.name.lower()
            
            if tag == "br":
                return "\n"
                
            children_text = "".join(render_element(child) for child in element.children)
            
            # Format based on tag type
            if tag in ["div", "p", "tr"]:
                return children_text + "\n"
            elif tag == "li":
                return "• " + children_text + "\n"
            elif tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                underline = "=" * max(len(children_text), 15)
                return f"\n\n{children_text.upper()}\n{underline}\n"
            elif tag == "blockquote":
                lines = children_text.strip().split("\n")
                return "\n" + "\n".join(f"> {line}" for line in lines) + "\n"
            elif tag == "hr":
                return "\n---\n"
            elif tag in ["table", "tbody"]:
                return children_text + "\n"
            elif tag == "td":
                return children_text + "  |  "
                
            return children_text

        raw_text = render_element(soup)
        
        # Collapse multiple blank lines to a maximum of one blank line, and trim
        text = re.sub(r'\n{3,}', '\n\n', raw_text).strip()
        return text
    except Exception as e:
        print(f"Warning: Failed to parse note content XML. Falling back to simple tag stripping. Error: {e}")
        # Very simple fallback: strip all XML tags
        return re.sub('<[^<]+?>', '', content_xml).strip()


def split_note_text(text, chunk_limit=18000):
    """
    Splits long text into chunks of at most chunk_limit characters.
    Splits at newline boundaries whenever possible to preserve formatting.
    """
    if len(text) <= chunk_limit:
        return [text]
        
    chunks = []
    lines = text.split("\n")
    current_chunk = []
    current_length = 0
    
    for line in lines:
        line_len = len(line) + 1  # Including the newline character
        if current_length + line_len > chunk_limit:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_length = line_len
            else:
                # If a single line is too long, we must split it by character
                sub_chunks = [line[i:i+chunk_limit] for i in range(0, len(line), chunk_limit)]
                for sc in sub_chunks[:-1]:
                    chunks.append(sc)
                current_chunk = [sub_chunks[-1]]
                current_length = len(sub_chunks[-1]) + 1
        else:
            current_chunk.append(line)
            current_length += line_len
            
    if current_chunk:
        chunks.append("\n".join(current_chunk))
        
    return chunks


def stream_evernote_notes(enex_path):
    """
    Generator function that steam-parses Evernote notes using iterparse.
    This keeps the memory footprint low even when processing a massive (1.1GB+) file.
    """
    try:
        context = ET.iterparse(enex_path, events=("start", "end"))
        context = iter(context)
        event, root = next(context)
    except Exception as e:
        print(f"Error opening/parsing XML file '{enex_path}': {e}")
        sys.exit(1)
        
    for event, elem in context:
        if event == "end" and elem.tag == "note":
            title = elem.findtext("title") or "Untitled Note"
            created = elem.findtext("created") or ""
            updated = elem.findtext("updated") or ""
            content_xml = elem.findtext("content") or ""
            tags = [tag.text for tag in elem.findall("tag") if tag.text]
            
            # Extract resources
            resources = []
            for r in elem.findall("resource"):
                mime = r.findtext("mime") or "application/octet-stream"
                
                data_elem = r.find("data")
                data_b64 = data_elem.text if data_elem is not None else ""
                
                attr = r.find("resource-attributes")
                file_name = None
                if attr is not None:
                    file_name = attr.findtext("file-name")
                    
                resources.append({
                    "mime": mime,
                    "data_b64": data_b64,
                    "file_name": file_name
                })
                
            yield {
                "title": title,
                "created": created,
                "updated": updated,
                "content": content_xml,
                "tags": tags,
                "resources": resources
            }
            
            # CRITICAL memory clearing: free elements and clear roots to prevent RAM leakage
            elem.clear()
            root.clear()


def main():
    args = parse_args()

    # Token setup wizard (no import)
    if args.setup_token:
        setup_master_token(email=args.email, token_path=args.token_file)
        return

    print("==============================================")
    print("      Evernote to Google Keep Importer        ")
    print("==============================================")
    print(f"ENEX file:           {args.enex}")
    print(f"Batch size:          {args.batch_size}")
    print(f"Note size limit:     {args.chunk_limit} chars")
    print(f"Dry-run:             {args.dry_run}")
    print(f"Upload images:       {args.upload_images}")
    print("==============================================")

    if args.upload_images:
        print(
            "Note: gkeepapi does not support uploading images to Keep notes. "
            "Attachments will still be extracted to disk and listed in note text."
        )

    # 1. Initialize state / Resume cache
    imported_cache = {}
    if not args.no_cache and os.path.exists(args.cache_file):
        try:
            with open(args.cache_file, "r", encoding="utf-8") as f:
                imported_cache = json.load(f)
            print(f"Loaded resume cache: {len(imported_cache)} notes previously imported.")
        except Exception as e:
            print(f"Warning: Failed to load resume cache: {e}")

    # 2. Authenticate Google Keep (Skip if Dry Run)
    keep = None
    keep_labels = {}  # Cache labels locally to minimize API roundtrips

    if not args.dry_run:
        # Resolve email + master token from CLI / env / token file
        email = args.email or os.environ.get("GOOGLE_EMAIL") or os.environ.get("KEEP_EMAIL")
        master_token = (
            args.master_token
            or os.environ.get("GOOGLE_MASTER_TOKEN")
            or os.environ.get("KEEP_MASTER_TOKEN")
        )

        file_email, file_token = load_token_file(args.token_file)
        if not email and file_email:
            email = file_email
        if not master_token and file_token:
            master_token = file_token
            print(f"Loaded master token from {args.token_file}")

        if not email:
            email = input("Enter your Google Account Email: ").strip()

        if not master_token:
            print("\nNo master token found.")
            print("Password login is no longer supported by gkeepapi/Google.")
            print_token_setup_instructions()
            choice = input("Run interactive token setup now? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                email, master_token = setup_master_token(email=email, token_path=args.token_file)
            else:
                print("Cannot continue without a master token. Exiting.")
                sys.exit(1)

        keep = authenticate_keep(email, master_token, skip_initial_sync=args.skip_initial_sync)

        # Ensure token file is in the modern JSON form for next runs
        try:
            save_token_file(args.token_file, email, master_token)
        except Exception as e:
            print(f"Warning: Could not save master token: {e}")

        # Cache existing labels (populated by authenticate's initial sync unless skipped)
        print("Caching existing Google Keep labels...")
        for label in keep.labels():
            keep_labels[label.name.lower()] = label
        print(f"Cached {len(keep_labels)} existing Keep labels.")
        if args.skip_initial_sync and not keep_labels:
            print(
                "  (Initial sync skipped — labels will be created as needed "
                "and applied on the next batch sync.)"
            )
        
    # 3. Setup attachment extraction path
    if args.attachments_dir:
        os.makedirs(args.attachments_dir, exist_ok=True)
        
    # 4. Start streaming and processing notes
    total_processed = 0
    imported_count = 0
    skipped_count = 0
    failed_count = 0
    attachments_saved = 0
    images_uploaded = 0
    notes_split_count = 0
    
    print("\nProcessing notes... (Press Ctrl+C to safely pause and save progress)")
    
    batch_dirty = False
    batch_note_count = 0
    
    try:
        for raw_note in stream_evernote_notes(args.enex):
            title = raw_note["title"]
            created = raw_note["created"]
            updated = raw_note["updated"]
            tags = raw_note["tags"]
            resources = raw_note["resources"]
            
            # Generate unique fingerprint
            fingerprint = get_note_fingerprint(title, created)
            
            # Check cache
            if fingerprint in imported_cache and not args.no_cache:
                skipped_count += 1
                total_processed += 1
                if args.limit and total_processed >= args.limit:
                    break
                continue
                
            print(f"\n[{total_processed + 1}] Processing: '{title}'")
            
            try:
                # Format timestamps
                fmt_created = format_timestamp(created)
                fmt_updated = format_timestamp(updated)
                
                # Convert content from ENML HTML to clean Plain Text
                plain_text = convert_enml_to_plain_text(raw_note["content"])
                
                # Extract and save attachments locally
                local_attachments = []
                note_dir_name = sanitize_name(title)
                if len(note_dir_name) > 60:  # Truncate folder name if too long
                    note_dir_name = note_dir_name[:60]
                
                for idx, r in enumerate(resources):
                    mime = r["mime"]
                    data_b64 = r["data_b64"]
                    file_name = r["file_name"]
                    
                    if not data_b64:
                        continue
                        
                    # Auto-generate file name if missing
                    if not file_name:
                        ext = mime.split("/")[-1] if "/" in mime else "bin"
                        if ext == "octet-stream":
                            ext = "bin"
                        file_name = f"attachment_{idx+1}.{ext}"
                        
                    file_name = sanitize_name(file_name)
                    
                    # Create note subdirectory for attachments
                    note_dir = os.path.join(args.attachments_dir, note_dir_name)
                    os.makedirs(note_dir, exist_ok=True)
                    
                    target_file_path = os.path.join(note_dir, file_name)
                    # Deduplicate filenames in same directory
                    counter = 1
                    base, ext = os.path.splitext(file_name)
                    while os.path.exists(target_file_path):
                        target_file_path = os.path.join(note_dir, f"{base}_{counter}{ext}")
                        counter += 1
                        
                    # Decode and save
                    try:
                        binary_data = base64.b64decode(re.sub(r'\s+', '', data_b64))
                        with open(target_file_path, "wb") as f:
                            f.write(binary_data)
                        local_attachments.append((target_file_path, mime))
                        attachments_saved += 1
                    except Exception as res_err:
                        print(f"  Error decoding attachment {file_name}: {res_err}")
                
                # Build note suffix (metadata and local attachments list)
                metadata_suffix = []
                metadata_suffix.append("\n\n---")
                metadata_suffix.append(f"Imported from Evernote")
                if fmt_created != "Unknown":
                    metadata_suffix.append(f"Original Created: {fmt_created}")
                if fmt_updated != "Unknown" and fmt_updated != fmt_created:
                    metadata_suffix.append(f"Original Updated: {fmt_updated}")
                    
                if local_attachments:
                    metadata_suffix.append("\nLocal Attachments:")
                    for path, _ in local_attachments:
                        # Store relative or absolute path based on workspace
                        rel_path = os.path.relpath(path, _PROJECT_DIR)
                        metadata_suffix.append(f"- {rel_path}")
                        
                if tags:
                    tag_line = " ".join([f"#{sanitize_name(t)}" for t in tags])
                    metadata_suffix.append(f"\nTags: {tag_line}")
                    
                suffix_text = "\n".join(metadata_suffix)
                
                # Check note length and split if it exceeds limit
                # Leave room for the suffix
                avail_space = args.chunk_limit - len(suffix_text) - 100
                if avail_space <= 2000:  # Defensive fallback
                    avail_space = 10000
                    
                text_chunks = split_note_text(plain_text, avail_space)
                num_chunks = len(text_chunks)
                
                if num_chunks > 1:
                    print(f"  Note is long ({len(plain_text)} chars). Splitting into {num_chunks} parts.")
                    notes_split_count += 1
                    
                # Create notes in Google Keep (or print details if dry-run)
                created_notes = []
                
                for idx, chunk in enumerate(text_chunks):
                    # Set part-specific title if split
                    note_title = title
                    if num_chunks > 1:
                        note_title = f"{title} (Part {idx+1}/{num_chunks})"
                        
                    # Only append metadata suffix to the last chunk
                    full_note_text = chunk
                    if idx == num_chunks - 1:
                        full_note_text += suffix_text
                        
                    if args.dry_run:
                        print(f"  [Dry-Run] Would create note: '{note_title}' ({len(full_note_text)} chars)")
                        created_notes.append(None)
                    else:
                        # Create note via gkeepapi
                        keep_note = keep.createNote(title=note_title, text=full_note_text)
                        created_notes.append(keep_note)
                        
                        # Add tags/labels to the note
                        for t in tags:
                            sanitized_tag = t.strip().lower()
                            if not sanitized_tag:
                                continue
                            
                            # Cache-lookup or create label
                            if sanitized_tag not in keep_labels:
                                try:
                                    # Create label in Google Keep
                                    # Limit name length if needed
                                    label_name = t.strip()[:30] # Keep limits label length
                                    new_label = keep.createLabel(label_name)
                                    keep_labels[sanitized_tag] = new_label
                                    print(f"  Created new Keep label: '{label_name}'")
                                except Exception as label_err:
                                    print(f"  Warning: Failed to create Keep label '{t}': {label_err}")
                                    continue
                                    
                            label_obj = keep_labels.get(sanitized_tag)
                            if label_obj:
                                keep_note.labels.add(label_obj)
                                
                        batch_dirty = True
                        batch_note_count += 1
                        
                # Image upload is not implemented in gkeepapi (unstable stub only).
                # Attachments are already extracted to disk and referenced in note text.
                if args.upload_images and not args.dry_run and local_attachments:
                    image_count = sum(1 for _, mime in local_attachments if mime.startswith("image/"))
                    if image_count:
                        print(
                            f"  Skipping {image_count} image upload(s): "
                            "gkeepapi has no working image upload API. "
                            "Files are listed under Local Attachments in the note."
                        )

                # Import successful, update tracking
                imported_count += 1
                imported_cache[fingerprint] = {
                    "title": title,
                    "imported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "split_parts": num_chunks,
                    "attachments_count": len(local_attachments)
                }
                
                # Periodic batch syncing to optimize API calls
                if not args.dry_run and batch_note_count >= args.batch_size:
                    print(f"Syncing batch of {batch_note_count} notes with Google Keep...")
                    keep.sync()
                    batch_dirty = False
                    batch_note_count = 0
                    # Save progress cache on successful sync
                    with open(args.cache_file, "w", encoding="utf-8") as f:
                        json.dump(imported_cache, f, indent=2)
                        
            except Exception as note_err:
                print(f"  ERROR processing note '{title}': {note_err}")
                failed_count += 1
                
            total_processed += 1
            if args.limit and total_processed >= args.limit:
                print(f"Limit of {args.limit} notes reached. Stopping.")
                break
                
    except KeyboardInterrupt:
        print("\n\nImport paused by user (KeyboardInterrupt). Saving state and syncing...")
        
    # 5. Final sync and cleanup
    if not args.dry_run:
        if batch_dirty:
            print("Syncing final batch with Google Keep...")
            try:
                keep.sync()
                print("Sync complete.")
            except Exception as sync_err:
                print(f"Error during final sync: {sync_err}")
                
        # Save cache
        try:
            with open(args.cache_file, "w", encoding="utf-8") as f:
                json.dump(imported_cache, f, indent=2)
            print(f"Progress saved to cache: {args.cache_file}")
        except Exception as cache_err:
            print(f"Warning: Failed to save progress cache: {cache_err}")
            
    # 6. Beautiful summary report
    print("\n==============================================")
    print("               IMPORT SUMMARY                 ")
    print("==============================================")
    print(f"Total processed:      {total_processed}")
    print(f"Successfully imported: {imported_count}")
    print(f"Skipped (cached):     {skipped_count}")
    print(f"Split notes count:    {notes_split_count}")
    print(f"Attachments extracted:{attachments_saved}")
    if args.upload_images and not args.dry_run:
        print(f"Images uploaded:      {images_uploaded}")
    print(f"Failed notes:         {failed_count}")
    print("==============================================")
    print("Process finished successfully!")

if __name__ == "__main__":
    main()
