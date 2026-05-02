#!/usr/bin/env python3
"""
Analyse an Obsidian vault: tag contacts, extract themes and trends.

Run after apple_notes_to_obsidian.py:
    python3 organise_vault.py [--vault PATH]

Produces:
    - YAML tags on every note  (theme/X, person/X)
    - People/<Name>.md         contact summary with backlinks
    - _Dashboard.md            top themes, contacts, stats
    - _Map-of-Content.md       notes grouped by theme cluster
"""

import argparse
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ── Stop words ────────────────────────────────────────────────────────────────

_STOP = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "i", "you",
    "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "this", "that", "these",
    "those", "what", "which", "who", "when", "where", "why", "how", "all",
    "each", "every", "both", "few", "more", "most", "other", "some", "no",
    "not", "only", "same", "so", "than", "too", "very", "just", "about",
    "also", "as", "because", "before", "after", "between", "into", "through",
    "then", "there", "here", "now", "any", "get", "got", "like", "make",
    "made", "one", "two", "new", "old", "first", "last", "time", "year",
    "day", "way", "use", "used", "see", "go", "come", "take", "think",
    "know", "want", "look", "good", "well", "note", "notes", "source",
    "title", "created", "modified", "true", "false", "apple",
}


# ── Vault reading ─────────────────────────────────────────────────────────────

def read_vault(vault_dir: Path) -> dict[Path, dict]:
    """Read all user .md files; skip generated (_) files."""
    notes: dict[Path, dict] = {}
    generated = {"_dashboard.md", "_map-of-content.md"}
    for md in vault_dir.rglob("*.md"):
        if md.name.lower() in generated or md.name.startswith("_"):
            continue
        if md.parts[len(vault_dir.parts):][0:1] == ("People",):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        notes[md] = _parse_note(text)
    return notes


def _parse_note(text: str) -> dict:
    fm: dict = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip('"')
            body = text[end + 5:]
    return {"frontmatter": fm, "body": body, "raw": text}


# ── Text utilities ────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    return [w for w in words if w not in _STOP]


def slugify(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()


def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")[:100]


# ── Apple Contacts ────────────────────────────────────────────────────────────

def get_apple_contacts() -> list[str]:
    """Return full names from Apple Contacts via AppleScript."""
    script = """\
tell application "Contacts"
    set output to {}
    repeat with p in people
        set fn to ""
        set ln to ""
        try
            set fn to first name of p
        end try
        try
            set ln to last name of p
        end try
        set full to (fn & " " & ln)
        set end of output to full
    end repeat
    return output
end tell"""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return [n.strip() for n in r.stdout.strip().split(",") if len(n.strip()) > 2]
    except Exception:
        pass
    return []


# ── Contact detection ─────────────────────────────────────────────────────────

def find_contact_mentions(
    notes: dict[Path, dict],
    contacts: list[str],
) -> dict[str, list[Path]]:
    """Map contact name -> notes that mention them."""
    mentions: dict[str, list[Path]] = defaultdict(list)
    patterns = {
        name: re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for name in contacts
        if len(name) >= 3
    }
    for path, note in notes.items():
        text = note["body"]
        for name, pat in patterns.items():
            if pat.search(text):
                mentions[name].append(path)
    return {k: v for k, v in mentions.items() if v}


def extract_emails(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", text)


def extract_phones(text: str) -> list[str]:
    return re.findall(
        r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", text
    )


# ── TF-IDF theme extraction ───────────────────────────────────────────────────

def compute_tfidf(notes: dict[Path, dict]) -> dict[Path, list[tuple[str, float]]]:
    """Top-10 TF-IDF terms per note."""
    doc_tokens = {p: tokenize(n["body"]) for p, n in notes.items()}
    df: Counter = Counter()
    for tokens in doc_tokens.values():
        df.update(set(tokens))
    N = max(len(doc_tokens), 1)

    results: dict[Path, list[tuple[str, float]]] = {}
    for path, tokens in doc_tokens.items():
        if not tokens:
            results[path] = []
            continue
        tf = Counter(tokens)
        scores = {
            w: (c / len(tokens)) * (math.log((N + 1) / (df[w] + 1)) + 1)
            for w, c in tf.items()
        }
        results[path] = sorted(scores.items(), key=lambda x: -x[1])[:10]
    return results


def global_themes(notes: dict[Path, dict], top_n: int = 30) -> list[tuple[str, int]]:
    """Most frequent meaningful terms across the whole vault."""
    all_tokens: list[str] = []
    for n in notes.values():
        all_tokens.extend(tokenize(n["body"]))
    return Counter(all_tokens).most_common(top_n)


def theme_clusters(tfidf: dict[Path, list[tuple[str, float]]]) -> dict[str, list[Path]]:
    """Group notes by their top TF-IDF term; keep clusters with ≥2 notes."""
    clusters: dict[str, list[Path]] = defaultdict(list)
    for path, terms in tfidf.items():
        for word, _ in terms[:5]:
            clusters[word].append(path)
    return {k: v for k, v in clusters.items() if len(v) >= 2}


# ── Frontmatter tagging ───────────────────────────────────────────────────────

def update_tags(path: Path, tags: list[str]) -> None:
    if not tags:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    tag_yaml = "tags: [" + ", ".join(tags) + "]"
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            fm_lines = [
                l for l in text[4:end].splitlines() if not l.startswith("tags:")
            ]
            fm_lines.append(tag_yaml)
            body = text[end + 5:]
            path.write_text("---\n" + "\n".join(fm_lines) + "\n---\n\n" + body, encoding="utf-8")
            return
    path.write_text(f"---\n{tag_yaml}\n---\n\n{text}", encoding="utf-8")


# ── Generated files ───────────────────────────────────────────────────────────

def write_contact_note(vault_dir: Path, name: str, paths: list[Path]) -> None:
    people_dir = vault_dir / "People"
    people_dir.mkdir(exist_ok=True)
    links = "\n".join(f"- [[{p.stem}]]" for p in sorted(paths, key=lambda p: p.stem))
    content = (
        f"---\ntags: [person]\n---\n\n"
        f"# {name}\n\n"
        f"## Mentioned in\n\n{links}\n"
    )
    (people_dir / f"{safe_filename(name)}.md").write_text(content, encoding="utf-8")


def write_dashboard(
    vault_dir: Path,
    note_count: int,
    themes: list[tuple[str, int]],
    contact_map: dict[str, list[Path]],
    clusters: dict[str, list[Path]],
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")

    theme_rows = "\n".join(f"| {w} | {c} |" for w, c in themes[:20])

    top_contacts = sorted(contact_map.items(), key=lambda x: -len(x[1]))[:30]
    contact_lines = "\n".join(
        f"- [[People/{safe_filename(name)}|{name}]] — {len(paths)} note{'s' if len(paths) != 1 else ''}"
        for name, paths in top_contacts
    )

    cluster_summary = "\n".join(
        f"- **{k}** ({len(v)} notes)" for k, v in
        sorted(clusters.items(), key=lambda x: -len(x[1]))[:15]
    )

    content = f"""\
---
generated: {today}
tags: [dashboard]
---

# Vault Dashboard

**{note_count} notes** · **{len(contact_map)} contacts tagged** · Generated {today}

---

## Top Themes

| Theme | Occurrences |
|-------|-------------|
{theme_rows}

---

## Theme Clusters

{cluster_summary}

---

## Contacts ({len(contact_map)})

{contact_lines}

---

*Re-run `organise_vault.py` to refresh.*
"""
    (vault_dir / "_Dashboard.md").write_text(content, encoding="utf-8")


def write_map_of_content(
    vault_dir: Path,
    clusters: dict[str, list[Path]],
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    sections: list[str] = []
    for theme, paths in sorted(clusters.items(), key=lambda x: -len(x[1]))[:40]:
        links = "\n".join(f"  - [[{p.stem}]]" for p in sorted(paths, key=lambda p: p.stem)[:25])
        sections.append(f"### {theme.capitalize()}\n\n{links}")

    content = (
        f"---\ngenerated: {today}\ntags: [moc]\n---\n\n"
        f"# Map of Content\n\n"
        + "\n\n".join(sections)
        + "\n"
    )
    (vault_dir / "_Map-of-Content.md").write_text(content, encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tag contacts and extract themes/trends from an Obsidian vault."
    )
    parser.add_argument(
        "--vault",
        default=str(Path.home() / "ObsidianVault"),
        help="Path to the Obsidian vault (default: ~/ObsidianVault)",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("Error: This script requires macOS (uses Apple Contacts).", file=sys.stderr)
        sys.exit(1)

    vault_dir = Path(args.vault).expanduser().resolve()
    if not vault_dir.exists():
        print(f"Vault not found: {vault_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Vault: {vault_dir}")

    print("Reading notes...")
    notes = read_vault(vault_dir)
    if not notes:
        print("No notes found.")
        return
    print(f"  {len(notes)} notes")

    print("Loading contacts from Apple Contacts...")
    raw_contacts = get_apple_contacts()
    print(f"  {len(raw_contacts)} contacts loaded")

    print("Scanning for contact mentions...")
    contact_map = find_contact_mentions(notes, raw_contacts)
    print(f"  {len(contact_map)} contacts mentioned across notes")

    print("Computing TF-IDF themes...")
    tfidf = compute_tfidf(notes)
    themes = global_themes(notes)
    clusters = theme_clusters(tfidf)
    print(f"  {len(clusters)} theme clusters")

    print("Tagging notes...")
    # Build per-note contact membership for fast lookup
    note_contacts: dict[Path, list[str]] = defaultdict(list)
    for name, paths in contact_map.items():
        for p in paths:
            note_contacts[p].append(name)

    for path, terms in tfidf.items():
        tags = [f"theme/{slugify(w)}" for w, _ in terms[:5] if w]
        tags += [f"person/{slugify(n)}" for n in note_contacts.get(path, [])]
        update_tags(path, tags)

    print("Creating People/ notes...")
    for name, paths in contact_map.items():
        write_contact_note(vault_dir, name, paths)

    print("Writing _Dashboard.md and _Map-of-Content.md...")
    write_dashboard(vault_dir, len(notes), themes, contact_map, clusters)
    write_map_of_content(vault_dir, clusters)

    print(f"\nDone.")
    print(f"  {len(contact_map)} contacts tagged  →  People/")
    print(f"  {len(clusters)} theme clusters  →  _Map-of-Content.md")
    print(f"  Open _Dashboard.md in Obsidian for an overview")


if __name__ == "__main__":
    main()
