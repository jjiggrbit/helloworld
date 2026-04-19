#!/usr/bin/env python3
"""
Transfer Apple Notes to an Obsidian-compatible vault.

Usage:
    python3 apple_notes_to_obsidian.py [--vault PATH] [--folder FOLDER]

Requirements:
    - macOS with Apple Notes app
    - Python 3.8+
    - Terminal granted Automation access to Notes in System Settings
"""

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path


# ── HTML → Markdown ──────────────────────────────────────────────────────────

class _HTMLToMarkdown(HTMLParser):
    """Convert Apple Notes HTML body to Markdown."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._tag_stack: list[str] = []
        self._list_stack: list[str] = []
        self._ol_counters: list[int] = []
        self._in_pre = False
        self._a_href = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._tag_stack.append(tag)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self._parts.append("\n\n")
        elif tag == "br":
            self._parts.append("  \n")
        elif tag in ("b", "strong"):
            self._parts.append("**")
        elif tag in ("i", "em"):
            self._parts.append("*")
        elif tag in ("s", "strike", "del"):
            self._parts.append("~~")
        elif tag == "u":
            self._parts.append("<u>")
        elif tag == "a":
            self._a_href = attrs_dict.get("href", "")
            self._parts.append("[")
        elif tag == "ul":
            self._list_stack.append("ul")
            self._parts.append("\n")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._ol_counters.append(0)
            self._parts.append("\n")
        elif tag == "li":
            indent = "  " * (len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ol_counters[-1] += 1
                self._parts.append(f"\n{indent}{self._ol_counters[-1]}. ")
            else:
                self._parts.append(f"\n{indent}- ")
        elif tag == "pre":
            self._in_pre = True
            self._parts.append("\n```\n")
        elif tag == "code" and not self._in_pre:
            self._parts.append("`")
        elif tag == "blockquote":
            self._parts.append("\n> ")
        elif tag == "hr":
            self._parts.append("\n---\n")
        elif tag == "div":
            self._parts.append("\n")
        elif tag in ("th", "td"):
            self._parts.append("| ")
        elif tag == "img":
            alt = attrs_dict.get("alt", "image")
            src = attrs_dict.get("src", "")
            self._parts.append(f"![{alt}]({src})")

    def handle_endtag(self, tag):
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")
        elif tag == "p":
            self._parts.append("\n")
        elif tag in ("b", "strong"):
            self._parts.append("**")
        elif tag in ("i", "em"):
            self._parts.append("*")
        elif tag in ("s", "strike", "del"):
            self._parts.append("~~")
        elif tag == "u":
            self._parts.append("</u>")
        elif tag == "a":
            self._parts.append(f"]({self._a_href})")
            self._a_href = ""
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            if tag == "ol" and self._ol_counters:
                self._ol_counters.pop()
            self._parts.append("\n")
        elif tag == "pre":
            self._in_pre = False
            self._parts.append("\n```\n")
        elif tag == "code" and not self._in_pre:
            self._parts.append("`")
        elif tag == "tr":
            self._parts.append("|\n")
        elif tag == "table":
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def handle_entityref(self, name):
        entities = {
            "amp": "&", "lt": "<", "gt": ">", "quot": '"',
            "apos": "'", "nbsp": "\u00a0", "mdash": "\u2014",
            "ndash": "\u2013", "ldquo": "\u201c", "rdquo": "\u201d",
            "lsquo": "\u2018", "rsquo": "\u2019",
        }
        self._parts.append(entities.get(name, f"&{name};"))

    def handle_charref(self, name):
        try:
            char = chr(int(name[1:], 16) if name.startswith("x") else int(name))
            self._parts.append(char)
        except (ValueError, OverflowError):
            pass

    def get_markdown(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html: str) -> str:
    parser = _HTMLToMarkdown()
    parser.feed(html)
    return parser.get_markdown()


# ── Utilities ────────────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name[:200] or "Untitled"


def run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def parse_applescript_date(date_str: str) -> str:
    """Convert AppleScript date string to ISO 8601."""
    formats = [
        "%A, %B %d, %Y at %I:%M:%S %p",
        "%A, %B %d, %Y at %H:%M:%S",
        "%B %d, %Y at %I:%M:%S %p",
        "%B %d, %Y at %H:%M:%S",
        "%m/%d/%Y, %I:%M:%S %p",
        "%m/%d/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return date_str


# ── AppleScript export ───────────────────────────────────────────────────────

_EXPORT_SCRIPT = """\
tell application "Notes"
    set exportDir to "{export_dir}"
    do shell script "mkdir -p " & quoted form of exportDir
    set noteIndex to 0
    set foldersToProcess to every folder
    {folder_filter}
    repeat with f in foldersToProcess
        set folderName to name of f
        repeat with n in notes of f
            set noteIndex to noteIndex + 1
            set idxStr to noteIndex as text
            set bodyPath to exportDir & "/" & idxStr & ".html"
            set metaPath to exportDir & "/" & idxStr & ".meta"
            try
                set bodyRef to open for access POSIX file bodyPath with write permission
                write (body of n) to bodyRef
                close access bodyRef
            on error
                try
                    close access POSIX file bodyPath
                end try
            end try
            try
                set metaContent to folderName & tab & (name of n) & tab & (creation date of n as text) & tab & (modification date of n as text)
                set metaRef to open for access POSIX file metaPath with write permission
                write metaContent to metaRef
                close access metaRef
            on error
                try
                    close access POSIX file metaPath
                end try
            end try
        end repeat
    end repeat
    return noteIndex as text
end tell
"""


def export_notes(export_dir: Path, folder_filter: str | None) -> int:
    if folder_filter:
        safe = folder_filter.replace('"', '\\"')
        filter_code = f'set foldersToProcess to (every folder whose name is "{safe}")'
    else:
        filter_code = ""
    script = _EXPORT_SCRIPT.format(export_dir=str(export_dir), folder_filter=filter_code)
    result = run_applescript(script)
    try:
        return int(result)
    except ValueError:
        return 0


# ── Note conversion ──────────────────────────────────────────────────────────

def write_note(meta_file: Path, body_file: Path, vault_dir: Path) -> bool:
    try:
        parts = meta_file.read_text(encoding="utf-8", errors="replace").split("\t", 3)
        parts += [""] * (4 - len(parts))
        folder_name, title, created, modified = parts
    except Exception:
        return False

    html = ""
    if body_file.exists():
        try:
            html = body_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    markdown = html_to_markdown(html)
    created_iso = parse_applescript_date(created)
    modified_iso = parse_applescript_date(modified)
    safe_title = title.replace('"', '\\"')

    content = (
        f'---\n'
        f'title: "{safe_title}"\n'
        f'created: {created_iso}\n'
        f'modified: {modified_iso}\n'
        f'source: Apple Notes\n'
        f'---\n\n'
        f'{markdown}\n'
    )

    folder_dir = vault_dir / sanitize_filename(folder_name) if folder_name.strip() else vault_dir
    folder_dir.mkdir(parents=True, exist_ok=True)

    base = sanitize_filename(title or "Untitled")
    out_path = folder_dir / f"{base}.md"
    counter = 1
    while out_path.exists():
        out_path = folder_dir / f"{base} ({counter}).md"
        counter += 1

    out_path.write_text(content, encoding="utf-8")
    return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Export Apple Notes to an Obsidian vault (Markdown files)."
    )
    parser.add_argument(
        "--vault",
        default=str(Path.home() / "ObsidianVault"),
        help="Destination Obsidian vault directory (default: ~/ObsidianVault)",
    )
    parser.add_argument(
        "--folder",
        default=None,
        metavar="NAME",
        help="Export only this Apple Notes folder (default: all folders)",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("Error: This script requires macOS.", file=sys.stderr)
        sys.exit(1)

    vault_dir = Path(args.vault).expanduser().resolve()
    vault_dir.mkdir(parents=True, exist_ok=True)

    print(f"Vault: {vault_dir}")
    if args.folder:
        print(f"Folder filter: {args.folder}")

    with tempfile.TemporaryDirectory(prefix="apple_notes_") as tmp:
        tmp_path = Path(tmp)

        print("Reading notes from Apple Notes (this may take a moment)...")
        try:
            count = export_notes(tmp_path, args.folder)
        except RuntimeError as e:
            print(f"\nError: {e}", file=sys.stderr)
            print(
                "\nTip: Grant Terminal (or your shell) Automation access to Notes in\n"
                "     System Settings → Privacy & Security → Automation",
                file=sys.stderr,
            )
            sys.exit(1)

        if count == 0:
            print("No notes found.")
            return

        print(f"Converting {count} notes to Markdown...")
        success = errors = 0
        for i in range(1, count + 1):
            ok = write_note(tmp_path / f"{i}.meta", tmp_path / f"{i}.html", vault_dir)
            if ok:
                success += 1
            else:
                errors += 1
            if success % 100 == 0 and success > 0:
                print(f"  {success}/{count}...")

    print(f"\nDone — {success} notes exported to: {vault_dir}")
    if errors:
        print(f"  ({errors} notes skipped due to errors)")


if __name__ == "__main__":
    main()
