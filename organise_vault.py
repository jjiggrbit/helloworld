#!/usr/bin/env python3
"""
Organise an Obsidian vault for personal insight and self-understanding.

Run after apple_notes_to_obsidian.py:
    python3 organise_vault.py [--vault PATH]

Produces:
    - YAML tags on every note        (area/X, theme/X, person/X)
    - People/<Name>.md               contact summary with backlinks + context
    - _Life-Areas/<Area>.md          notes grouped by life domain
    - _Timeline.md                   notes plotted by date
    - _About-Me.md                   synthesised personal profile
    - _Dashboard.md                  top themes, contacts, stats
"""

import argparse
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ── Life-area taxonomy ────────────────────────────────────────────────────────

LIFE_AREAS: dict[str, list[str]] = {
    "work": [
        "job", "work", "career", "project", "meeting", "client", "business",
        "office", "deadline", "manager", "team", "salary", "hire", "startup",
        "company", "product", "strategy", "boss", "colleague", "task", "revenue",
        "launch", "pitch", "investor", "contract", "invoice", "productivity",
    ],
    "health": [
        "health", "exercise", "gym", "run", "sleep", "diet", "food", "doctor",
        "pain", "anxiety", "stress", "mental", "therapy", "meditation", "yoga",
        "weight", "energy", "tired", "sick", "hospital", "medicine", "breath",
        "body", "fitness", "workout", "nutrition", "wellbeing",
    ],
    "relationships": [
        "friend", "family", "love", "relationship", "partner", "wife", "husband",
        "girlfriend", "boyfriend", "mom", "dad", "sister", "brother", "marriage",
        "dating", "social", "trust", "conversation", "conflict", "connection",
        "together", "support", "lonely", "community", "people",
    ],
    "finance": [
        "money", "invest", "savings", "budget", "debt", "income", "expense",
        "financial", "bank", "crypto", "stock", "cost", "pay", "afford", "rich",
        "poor", "rent", "mortgage", "spend", "earn", "profit", "loss", "tax",
        "insurance", "asset", "liability",
    ],
    "creativity": [
        "write", "writing", "art", "music", "design", "create", "build", "code",
        "draw", "paint", "photo", "film", "podcast", "blog", "idea", "creative",
        "story", "make", "craft", "express", "imagine", "invent", "produce",
    ],
    "learning": [
        "learn", "read", "book", "course", "study", "school", "university",
        "knowledge", "skill", "practice", "research", "understand", "curious",
        "explore", "insight", "concept", "theory", "question", "grow", "improve",
    ],
    "travel": [
        "travel", "trip", "city", "country", "flight", "hotel", "explore",
        "visit", "adventure", "vacation", "holiday", "abroad", "culture",
        "road", "journey", "destination", "place", "map",
    ],
    "reflection": [
        "feel", "think", "realize", "wonder", "believe", "values", "purpose",
        "meaning", "goal", "dream", "hope", "fear", "regret", "grateful",
        "happy", "sad", "angry", "peace", "identity", "growth", "change",
        "future", "past", "decision", "choice", "lesson",
    ],
    "ideas": [
        "idea", "concept", "theory", "hypothesis", "model", "framework",
        "system", "pattern", "principle", "insight", "observation", "thought",
        "perspective", "question", "problem", "solution", "opportunity",
    ],
}

# ── Insight patterns ──────────────────────────────────────────────────────────

_GOAL_RE = re.compile(
    r"(?:I (?:want|need|plan|intend|hope|would like) to|my goal is to|"
    r"I(?:'m| am) going to|I(?:'ll| will))\s+(.{5,80}?)(?:[.!\n]|$)",
    re.IGNORECASE,
)
_VALUE_RE = re.compile(
    r"(?:I (?:really |truly |deeply )?(?:care about|value|love|believe in|"
    r"think|feel|know)|what matters (?:most |to me )?is|"
    r"most important to me)\s+(.{5,80}?)(?:[.!\n]|$)",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"([A-Z][^.!?\n]{15,100}\?)")
_DECISION_RE = re.compile(
    r"(?:I (?:decided|chose|choose|realised|realized)|decided to)\s+(.{5,80}?)(?:[.!\n]|$)",
    re.IGNORECASE,
)
_SENTIMENT_POS = {
    "happy", "great", "love", "excited", "grateful", "proud", "joy", "good",
    "amazing", "wonderful", "fantastic", "excellent", "inspired", "motivated",
    "progress", "success", "achieved", "accomplished", "calm", "peaceful",
}
_SENTIMENT_NEG = {
    "sad", "angry", "frustrated", "stressed", "anxious", "worried", "fear",
    "tired", "exhausted", "overwhelmed", "lost", "stuck", "struggle", "fail",
    "difficult", "hard", "problem", "broken", "hate", "terrible", "bad",
    "regret", "lonely", "confused", "doubt",
}

# ── Stop words ────────────────────────────────────────────────────────────────

_STOP = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "i", "you", "he",
    "she", "it", "we", "they", "me", "him", "her", "us", "them", "my",
    "your", "his", "its", "our", "their", "this", "that", "these", "those",
    "what", "which", "who", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "no", "not",
    "only", "same", "so", "than", "too", "very", "just", "about", "also",
    "as", "because", "before", "after", "between", "into", "through", "then",
    "there", "here", "now", "any", "get", "got", "like", "make", "made",
    "one", "two", "new", "old", "first", "last", "time", "year", "day",
    "way", "use", "used", "see", "go", "come", "take", "think", "know",
    "want", "look", "good", "well", "note", "notes", "source", "title",
    "created", "modified", "true", "false", "apple", "thing", "things",
    "even", "still", "back", "really", "much", "many", "something", "someone",
    "people", "going", "feel", "felt", "said", "says", "just", "right",
    "let", "never", "always", "ever", "every", "again", "around", "put",
    "set", "actually", "already", "done", "dont", "didnt", "cant", "wont",
}


# ── Vault I/O ─────────────────────────────────────────────────────────────────

_GENERATED = {"_dashboard.md", "_about-me.md", "_timeline.md", "_map-of-content.md"}


def read_vault(vault_dir: Path) -> dict[Path, dict]:
    notes: dict[Path, dict] = {}
    for md in vault_dir.rglob("*.md"):
        if md.name.lower() in _GENERATED or md.name.startswith("_"):
            continue
        rel = md.relative_to(vault_dir)
        if rel.parts[0] in ("People", "_Life-Areas"):
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        notes[md] = _parse_note(text)
    return notes


def _parse_note(text: str) -> dict:
    fm: dict[str, str] = {}
    body = text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip('"')
            body = text[end + 5:]
    return {"frontmatter": fm, "body": body}


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
        set end of output to (fn & " " & ln)
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
    notes: dict[Path, dict], contacts: list[str]
) -> dict[str, list[tuple[Path, str]]]:
    """Map name -> [(note_path, sentence_snippet)] for context."""
    patterns = {
        name: re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for name in contacts if len(name) >= 3
    }
    mentions: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for path, note in notes.items():
        body = note["body"]
        sentences = re.split(r"(?<=[.!?\n])\s+", body)
        for name, pat in patterns.items():
            for sent in sentences:
                if pat.search(sent):
                    snippet = sent.strip()[:120]
                    mentions[name].append((path, snippet))
                    break  # one snippet per note per contact
    return {k: v for k, v in mentions.items() if v}


# ── Life area classification ──────────────────────────────────────────────────

def classify_areas(text: str) -> list[str]:
    """Return top ≤2 life areas for a note body."""
    words = set(re.findall(r"\b[a-zA-Z]{3,}\b", text.lower()))
    scores = {
        area: len(words & set(kws))
        for area, kws in LIFE_AREAS.items()
    }
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    # Return areas that scored > 0 and are within 2 of the top score
    if not ranked or ranked[0][1] == 0:
        return []
    top_score = ranked[0][1]
    return [a for a, s in ranked[:3] if s > 0 and s >= max(top_score - 2, 1)][:2]


# ── Insight extraction ────────────────────────────────────────────────────────

def extract_insights(notes: dict[Path, dict]) -> dict:
    goals: list[tuple[str, Path]] = []
    values: list[tuple[str, Path]] = []
    questions: list[tuple[str, Path]] = []
    decisions: list[tuple[str, Path]] = []

    for path, note in notes.items():
        body = note["body"]
        for m in _GOAL_RE.finditer(body):
            goals.append((m.group(1).strip(), path))
        for m in _VALUE_RE.finditer(body):
            values.append((m.group(1).strip(), path))
        for m in _QUESTION_RE.finditer(body):
            q = m.group(1).strip()
            if len(q) > 20:
                questions.append((q, path))
        for m in _DECISION_RE.finditer(body):
            decisions.append((m.group(1).strip(), path))

    return {
        "goals": goals[:40],
        "values": values[:30],
        "questions": questions[:40],
        "decisions": decisions[:30],
    }


def note_sentiment(body: str) -> str:
    words = set(re.findall(r"\b[a-zA-Z]+\b", body.lower()))
    pos = len(words & _SENTIMENT_POS)
    neg = len(words & _SENTIMENT_NEG)
    if pos > neg + 1:
        return "positive"
    if neg > pos + 1:
        return "challenging"
    return "neutral"


# ── TF-IDF ────────────────────────────────────────────────────────────────────

def compute_tfidf(notes: dict[Path, dict]) -> dict[Path, list[tuple[str, float]]]:
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
        results[path] = sorted(scores.items(), key=lambda x: -x[1])[:8]
    return results


def global_themes(notes: dict[Path, dict], top_n: int = 30) -> list[tuple[str, int]]:
    tokens: list[str] = []
    for n in notes.values():
        tokens.extend(tokenize(n["body"]))
    return Counter(tokens).most_common(top_n)


# ── Temporal analysis ─────────────────────────────────────────────────────────

def temporal_buckets(notes: dict[Path, dict]) -> dict[str, list[Path]]:
    """Group notes by YYYY-MM from their frontmatter created date."""
    buckets: dict[str, list[Path]] = defaultdict(list)
    for path, note in notes.items():
        created = note["frontmatter"].get("created", "")
        m = re.match(r"(\d{4}-\d{2})", created)
        if m:
            buckets[m.group(1)].append(path)
        else:
            buckets["unknown"].append(path)
    return dict(sorted(buckets.items()))


# ── Frontmatter tagging ───────────────────────────────────────────────────────

def update_tags(path: Path, tags: list[str]) -> None:
    if not tags:
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    tag_yaml = "tags: [" + ", ".join(dict.fromkeys(tags)) + "]"  # deduplicated
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            fm_lines = [l for l in text[4:end].splitlines() if not l.startswith("tags:")]
            fm_lines.append(tag_yaml)
            body = text[end + 5:]
            path.write_text("---\n" + "\n".join(fm_lines) + "\n---\n\n" + body, encoding="utf-8")
            return
    path.write_text(f"---\n{tag_yaml}\n---\n\n{text}", encoding="utf-8")


# ── Generated note writers ────────────────────────────────────────────────────

def write_contact_note(
    vault_dir: Path,
    name: str,
    mentions: list[tuple[Path, str]],
    all_notes: dict[Path, dict],
) -> None:
    people_dir = vault_dir / "People"
    people_dir.mkdir(exist_ok=True)

    # Find what areas/themes this person appears in
    area_counter: Counter = Counter()
    for path, _ in mentions:
        note = all_notes.get(path, {})
        areas = classify_areas(note.get("body", ""))
        area_counter.update(areas)

    context_section = ""
    if mentions:
        context_lines = "\n".join(
            f"- [[{p.stem}]] — *{snippet}*"
            for p, snippet in mentions[:20]
        )
        context_section = f"## Appears in\n\n{context_lines}\n"

    area_tags = ", ".join(f"`{a}`" for a, _ in area_counter.most_common(3)) or "—"
    content = (
        f"---\ntags: [person]\n---\n\n"
        f"# {name}\n\n"
        f"**Common contexts:** {area_tags}  \n"
        f"**Mentioned in:** {len(mentions)} note{'s' if len(mentions) != 1 else ''}\n\n"
        f"{context_section}"
    )
    (people_dir / f"{safe_filename(name)}.md").write_text(content, encoding="utf-8")


def write_life_area_moc(
    vault_dir: Path,
    area_notes: dict[str, list[Path]],
    themes: list[tuple[str, int]],
) -> None:
    la_dir = vault_dir / "_Life-Areas"
    la_dir.mkdir(exist_ok=True)

    for area, paths in area_notes.items():
        if not paths:
            continue
        links = "\n".join(f"- [[{p.stem}]]" for p in sorted(paths, key=lambda p: p.stem))
        # top keywords for this area subset
        content = (
            f"---\ntags: [area/{area}, moc]\n---\n\n"
            f"# {area.capitalize()}\n\n"
            f"**{len(paths)} notes**\n\n"
            f"## Notes\n\n{links}\n"
        )
        (la_dir / f"{area.capitalize()}.md").write_text(content, encoding="utf-8")


def write_timeline(vault_dir: Path, buckets: dict[str, list[Path]]) -> None:
    lines: list[str] = []
    for month, paths in sorted(buckets.items()):
        if month == "unknown":
            continue
        bar = "█" * min(len(paths), 40)
        lines.append(f"**{month}** `{bar}` {len(paths)}")
        for p in sorted(paths, key=lambda x: x.stem)[:5]:
            lines.append(f"  - [[{p.stem}]]")
        if len(paths) > 5:
            lines.append(f"  - *…and {len(paths) - 5} more*")

    content = (
        "---\ntags: [timeline]\n---\n\n"
        "# Timeline\n\n"
        + "\n".join(lines)
        + "\n"
    )
    (vault_dir / "_Timeline.md").write_text(content, encoding="utf-8")


def write_about_me(
    vault_dir: Path,
    insights: dict,
    themes: list[tuple[str, int]],
    area_counts: Counter,
    contact_map: dict[str, list],
    note_count: int,
    sentiment_counts: Counter,
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")

    # Top themes (filtered to feel personal)
    theme_list = "\n".join(f"- **{w}** ({c})" for w, c in themes[:15])

    # Life area breakdown
    total_area = sum(area_counts.values()) or 1
    area_lines = "\n".join(
        f"- **{a.capitalize()}** — {round(c / total_area * 100)}% of notes"
        for a, c in area_counts.most_common()
        if c > 0
    )

    # Goals
    goal_lines = "\n".join(
        f"- *{g}* ([[{p.stem}]])" for g, p in insights["goals"][:15]
    ) or "*(none detected)*"

    # Values
    value_lines = "\n".join(
        f"- *{v}* ([[{p.stem}]])" for v, p in insights["values"][:10]
    ) or "*(none detected)*"

    # Questions
    question_lines = "\n".join(
        f"- {q}" for q, _ in insights["questions"][:15]
    ) or "*(none detected)*"

    # Decisions
    decision_lines = "\n".join(
        f"- *{d}* ([[{p.stem}]])" for d, p in insights["decisions"][:10]
    ) or "*(none detected)*"

    # Top people
    top_people = sorted(contact_map.items(), key=lambda x: -len(x[1]))[:10]
    people_lines = "\n".join(
        f"- [[People/{safe_filename(name)}|{name}]] ({len(m)} notes)"
        for name, m in top_people
    ) or "*(none detected)*"

    # Sentiment
    pos = sentiment_counts.get("positive", 0)
    neu = sentiment_counts.get("neutral", 0)
    cha = sentiment_counts.get("challenging", 0)
    total_s = max(pos + neu + cha, 1)

    content = f"""\
---
generated: {today}
tags: [about-me, profile]
---

# About Me — Synthesised from Notes

*Auto-generated from {note_count} notes on {today}. Re-run `organise_vault.py` to refresh.*

---

## Where I spend my mental energy

{area_lines}

---

## What I think about most

{theme_list}

---

## What I want (goals)

{goal_lines}

---

## What I care about (values)

{value_lines}

---

## Questions I carry

{question_lines}

---

## Decisions I've made

{decision_lines}

---

## People in my life

{people_lines}

---

## Emotional tone of notes

| Tone | Notes | Share |
|------|-------|-------|
| Positive | {pos} | {round(pos/total_s*100)}% |
| Neutral | {neu} | {round(neu/total_s*100)}% |
| Challenging | {cha} | {round(cha/total_s*100)}% |

---

*For deeper navigation: [[_Dashboard]] · [[_Timeline]] · [[_Map-of-Content]]*
"""
    (vault_dir / "_About-Me.md").write_text(content, encoding="utf-8")


def write_dashboard(
    vault_dir: Path,
    note_count: int,
    themes: list[tuple[str, int]],
    area_counts: Counter,
    contact_map: dict[str, list],
    buckets: dict[str, list[Path]],
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    theme_rows = "\n".join(f"| {w} | {c} |" for w, c in themes[:20])
    area_rows = "\n".join(
        f"| {a.capitalize()} | {c} |" for a, c in area_counts.most_common()
    )
    top_contacts = sorted(contact_map.items(), key=lambda x: -len(x[1]))[:20]
    contact_lines = "\n".join(
        f"- [[People/{safe_filename(n)}|{n}]] ({len(m)})"
        for n, m in top_contacts
    )
    active_months = sorted(
        ((k, len(v)) for k, v in buckets.items() if k != "unknown"),
        key=lambda x: -x[1],
    )[:5]
    active_lines = "\n".join(f"- **{m}** — {c} notes" for m, c in active_months)

    content = f"""\
---
generated: {today}
tags: [dashboard]
---

# Dashboard

**{note_count} notes** · **{len(contact_map)} contacts** · {today}

→ [[_About-Me]] · [[_Timeline]] · [[_Map-of-Content]]

---

## Life Areas

| Area | Notes |
|------|-------|
{area_rows}

---

## Top Themes

| Theme | Occurrences |
|-------|-------------|
{theme_rows}

---

## Most Active Periods

{active_lines}

---

## People ({len(contact_map)})

{contact_lines}

---
*Re-run `organise_vault.py` to refresh.*
"""
    (vault_dir / "_Dashboard.md").write_text(content, encoding="utf-8")


def write_map_of_content(
    vault_dir: Path,
    area_notes: dict[str, list[Path]],
) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    sections: list[str] = []
    for area, paths in sorted(area_notes.items(), key=lambda x: -len(x[1])):
        links = "\n".join(
            f"  - [[{p.stem}]]" for p in sorted(paths, key=lambda p: p.stem)[:30]
        )
        sections.append(f"### {area.capitalize()} ({len(paths)})\n\n{links}")

    content = (
        f"---\ngenerated: {today}\ntags: [moc]\n---\n\n"
        "# Map of Content\n\n"
        + "\n\n".join(sections)
        + "\n"
    )
    (vault_dir / "_Map-of-Content.md").write_text(content, encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Organise Obsidian vault for personal insight."
    )
    parser.add_argument(
        "--vault",
        default=str(Path.home() / "ObsidianVault"),
        help="Path to the vault (default: ~/ObsidianVault)",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("Error: requires macOS.", file=sys.stderr)
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
    print(f"  {len(raw_contacts)} contacts")

    print("Scanning for contact mentions...")
    contact_map = find_contact_mentions(notes, raw_contacts)
    print(f"  {len(contact_map)} contacts mentioned")

    print("Classifying life areas...")
    area_notes: dict[str, list[Path]] = defaultdict(list)
    note_areas: dict[Path, list[str]] = {}
    area_counts: Counter = Counter()
    for path, note in notes.items():
        areas = classify_areas(note["body"])
        note_areas[path] = areas
        for a in areas:
            area_notes[a].append(path)
            area_counts[a] += 1

    print("Extracting personal insights...")
    insights = extract_insights(notes)
    print(
        f"  {len(insights['goals'])} goals, "
        f"{len(insights['values'])} values, "
        f"{len(insights['questions'])} questions, "
        f"{len(insights['decisions'])} decisions"
    )

    print("Computing themes (TF-IDF)...")
    tfidf = compute_tfidf(notes)
    themes = global_themes(notes)

    print("Analysing timeline...")
    buckets = temporal_buckets(notes)

    print("Tagging notes...")
    note_contacts: dict[Path, list[str]] = defaultdict(list)
    for name, mentions in contact_map.items():
        for path, _ in mentions:
            note_contacts[path].append(name)

    sentiment_counts: Counter = Counter()
    for path, note in notes.items():
        areas = note_areas.get(path, [])
        terms = tfidf.get(path, [])
        sentiment = note_sentiment(note["body"])
        sentiment_counts[sentiment] += 1

        tags = (
            [f"area/{a}" for a in areas]
            + [f"theme/{slugify(w)}" for w, _ in terms[:4] if w]
            + [f"person/{slugify(n)}" for n in note_contacts.get(path, [])]
            + [f"tone/{sentiment}"]
        )
        update_tags(path, tags)

    print("Creating People/ notes...")
    for name, mentions in contact_map.items():
        write_contact_note(vault_dir, name, mentions, notes)

    print("Writing _Life-Areas/...")
    write_life_area_moc(vault_dir, area_notes, themes)

    print("Writing _Timeline.md...")
    write_timeline(vault_dir, buckets)

    print("Writing _About-Me.md...")
    write_about_me(
        vault_dir, insights, themes, area_counts,
        contact_map, len(notes), sentiment_counts,
    )

    print("Writing _Dashboard.md and _Map-of-Content.md...")
    write_dashboard(vault_dir, len(notes), themes, area_counts, contact_map, buckets)
    write_map_of_content(vault_dir, area_notes)

    print(f"\nDone.")
    print(f"  Open _About-Me.md to see your synthesised profile")
    print(f"  Open _Dashboard.md for the overview")
    print(f"  Enable Obsidian Graph View to see the full connection map")


if __name__ == "__main__":
    main()
