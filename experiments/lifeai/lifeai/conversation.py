"""A narrow narrative channel: speech can carry stories, never an object snapshot."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

MAX_STORY_CHARS = 900
MAX_STORY_WORDS = 140
TALK_RANGE = 3
REPLY_WINDOW = 30.0


class RepeatedSpeech(ValueError):
    pass


def is_repetition(text: str, previous: str) -> bool:
    def words(value):
        return re.findall(r"\w+", value.casefold())
    a, b = words(text), words(previous)
    if a == b:
        return True
    # Only near-verbatim repetition; meaning is interpreted by the LLM.
    return (min(len(a), len(b)) >= 8 and
            SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() >= .83)


def dialogue_label(utterance: dict | None) -> str:
    if not utterance:
        return ""
    return {"new": "nowa wypowiedź do mnie; jeszcze jej nie rozważyłam",
            "considered": "rozważona wypowiedź; jeszcze na nią nie odpowiedziałam",
            "waiting": "moja wypowiedź; jeszcze nie usłyszałam odpowiedzi",
            "answered": "ta wypowiedź otrzymała odpowiedź",
            "unanswered": "dotąd bez odpowiedzi; nie wiem dlaczego",
            "lost_contact": "kontakt się urwał; nie usłyszałam odpowiedzi",
            "peer_dead": "rozmowa zakończona: widziałam, że rozmówca jest martwy; nie może odpowiedzieć",
            "past": "wcześniejsza kwestia rozmowy"}.get(utterance.get("state"), "")


class Dialogue:
    """Turn state references ordinary, budgeted prose nodes; no second transcript."""

    def __init__(self, owner):
        self.owner = owner

    def rows(self, peer=""):
        return [n for n in self.owner.memory.nodes if n.utterance and
                (not peer or n.utterance["peer_id"] == peer)]

    def incoming(self, peer=""):
        return next((n for n in reversed(self.rows(peer)) if n.utterance["direction"] == "received"
                     and n.utterance["state"] in ("new", "considered")), None)

    def waiting(self, peer):
        return next((n for n in reversed(self.rows(peer)) if n.utterance["state"] == "waiting"), None)

    def recent_contact(self, peer):
        return any(n.utterance["state"] != "peer_dead" and
                   (n.utterance["state"] in ("new", "considered", "waiting") or
                    self.owner.lifetime_seconds - n.utterance["at"] < REPLY_WINDOW) for n in self.rows(peer))

    def recognize_dead(self, peer):
        changed = False
        for node in self.rows(peer):
            if node.utterance["state"] in ("new", "considered", "waiting", "unanswered", "lost_contact"):
                node.utterance["state"] = "peer_dead"
                changed = True
        if changed:
            self.owner.memory._trim()
        return changed

    def received(self, node):
        reply_to = node.utterance.get("reply_to", "")
        for previous in self.rows(node.utterance["peer_id"]):
            if previous is node:
                continue
            if previous.utterance["id"] == reply_to:
                previous.utterance["state"] = "answered"
            elif previous.utterance["direction"] == "received":
                previous.utterance["state"] = "past"
        self.owner.memory._trim()

    def sent(self, reply_to):
        for node in self.rows():
            if node.utterance["id"] == reply_to:
                node.utterance["state"] = "answered"
        self.owner.memory._trim()

    def reviewed(self, ids):
        for node in self.rows():
            if node.id in ids and node.utterance["state"] == "new":
                node.utterance["state"] = "considered"
        self.owner.memory._trim()

    def expire(self, connected):
        changed = []
        for node in self.rows():
            info = node.utterance
            elapsed = self.owner.lifetime_seconds - info["at"]
            if info["state"] == "waiting" and (elapsed >= REPLY_WINDOW or not connected(info["peer_id"])):
                info["state"] = "unanswered" if elapsed >= REPLY_WINDOW else "lost_contact"
                changed.append(node)
        if changed:
            self.owner.memory._trim()
        return changed

    def snapshot(self, peer=""):
        def describe(node):
            info = node.utterance
            names = node.origins if info["direction"] == "received" else node.audience
            return {"memory_id": node.id, **info, "peer_name": names.get(info["peer_id"], info["peer_id"]),
                    "text": node.text, "elapsed": round(self.owner.lifetime_seconds - info["at"], 1)}
        rows = self.rows(peer)
        return {"turns": [describe(n) for n in rows[-6:]],
                "incoming": [describe(n) for n in rows if n.utterance["state"] in ("new", "considered")],
                "awaiting_reply": [describe(n) for n in rows if n.utterance["state"] == "waiting"]}


def validate_story(value: object, *, reply: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("Opowieść musi być tekstem.")
    text = value.strip()
    minimum_chars, minimum_words = (3, 1) if reply else (40, 8)
    if not minimum_chars <= len(text) <= MAX_STORY_CHARS:
        raise ValueError(f"Wypowiedź musi mieć {minimum_chars}–{MAX_STORY_CHARS} znaków.")
    if not minimum_words <= len(text.split()) <= MAX_STORY_WORDS:
        raise ValueError(f"Wypowiedź musi mieć {minimum_words}–{MAX_STORY_WORDS} słów.")
    # JSON, code, tables, enumerations, serialized fields and encoded payloads
    # cannot cross the communication boundary, even if wrapped in prose.
    if (any(c in text for c in "{}[]`|<>")
            or re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])\s", text)
            or re.search(r"[\w+/=.-]{40,}", text)
            or re.search(r"\b(?:episodes|knowledge|last_seen|strength|reinforce|weaken|"
                         r"estimated_tokens|memory|grid|tick|importance|summary|map|"
                         r"epizody|pamięć|mapa)\b[\"']?\s*[:=]", text, re.I)
            or any(ord(c) < 32 and c not in "\n\t" for c in text)
            or text.count("\n") > 2 or text.count(";") > 2):
        raise ValueError("Zakaz dumpu: opowiedz doświadczenie własnymi słowami, bez struktur danych.")
    if len(re.findall(r"-?\d+(?:[.,]\d+)?", text)) > 8:
        raise ValueError("Opowieść zawiera zbyt wiele liczb; opisz drogę i przeżycia słowami.")
    return " ".join(text.split())
