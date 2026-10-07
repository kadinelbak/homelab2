"""People profiles: free-text notes about people, split into tagged facts and read back grouped."""

from __future__ import annotations

import json
import re

KINDS = {
    "personality": "Personality",
    "key_moment": "Key moments",
    "likes": "Likes and interests",
    "life": "Life details",
    "follow_up": "Follow up next time",
    "other": "Other notes",
}

SYSTEM_PROMPT = (
    "You turn a user's note about people they spent time with into structured facts. "
    "Return only a JSON array. Each item is {\"person\": full name as the user refers to them, "
    "\"kind\": one of " + ", ".join(KINDS) + ", \"text\": one short fact in third person}. "
    "personality = traits and how they come across; key_moment = something that happened with or to them; "
    "likes = interests, tastes, preferences; life = job, family, where they live, plans; "
    "follow_up = things to ask about or remember next time. Skip facts about the user alone. "
    "If a known person matches, reuse their exact name."
)


def person_key(name: str) -> str:
    return " ".join(str(name or "").lower().split())


def guess_person(text: str) -> str | None:
    """Fallback when the model is unavailable: 'about Sam: ...', 'Sam: ...', 'with Sam ...'."""
    match = re.search(r"\b(?:about|with|met)\s+([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)", text) or re.match(r"\s*([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)\s*:", text)
    return match.group(1).strip() if match else None


def build_prompt(text: str, known_people: list[str]) -> str:
    known = ", ".join(known_people[:200]) or "none yet"
    return f"Known people: {known}\n\nNote:\n{text}"


def parse_facts(content: str, default_person: str | None = None) -> list[dict]:
    start, end = content.find("["), content.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        items = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return []
    facts = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        person = str(item.get("person") or default_person or "").strip()
        fact = str(item.get("text") or "").strip()
        kind = str(item.get("kind") or "other").strip().lower()
        if person and fact:
            facts.append({"person": person[:120], "kind": kind if kind in KINDS else "other", "text": fact})
    return facts


def organize(person: str, notes: list) -> dict:
    sections = {kind: [] for kind in KINDS}
    for note in sorted(notes, key=lambda n: n.noted_at):
        sections[note.kind if note.kind in KINDS else "other"].append(
            {"id": note.id, "text": note.text, "noted_at": note.noted_at.isoformat() if note.noted_at else None}
        )
    sections = {kind: items for kind, items in sections.items() if items}
    lines = [f"Here is what you've noted about {person}."]
    for kind, items in sections.items():
        lines.append(f"{KINDS[kind]}: " + "; ".join(item["text"].rstrip(".") for item in items[-5:]) + ".")
    return {"person": person, "note_count": len(notes), "sections": sections, "text": " ".join(lines)}
