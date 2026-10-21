"""Bounded contextual memory: prose nodes, relationships, and transient impressions."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field

from .conversation import dialogue_label, validate_story


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def estimate_tokens(value: object) -> int:
    text = value if isinstance(value, str) else compact_json(value)
    return math.ceil(len(text.encode("utf-8")) / 3)


@dataclass
class MemoryNode:
    id: int
    tick: int
    text: str
    links: list[int] = field(default_factory=list)
    strength: float = 1.0
    source: str = "insight"
    origins: dict[str, str] = field(default_factory=dict)
    rehearsals: int = 0
    audience: dict[str, str] = field(default_factory=dict)

    observation: dict | None = None
    utterance: dict | None = None
    experience: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Impression:
    id: int
    tick: int
    text: str
    importance: float = 0.4
    body: dict | None = None


def read_note(text: str, valid_ids: set[int], *, require_links: bool = False) -> tuple[str, list[int]]:
    if not isinstance(text, str) or not 25 <= len(text.strip()) <= 1800:
        raise ValueError("Zapisz spostrzeżenie prozą, w 25–1800 znakach.")
    if any(c in text for c in "{}`"):
        raise ValueError("Pamięć ma być prozą, nie JSON-em ani kodem.")
    if re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])\s", text):
        raise ValueError("Zapisz osobiste spostrzeżenie ciągłą prozą, bez listy kroków ani planu ruchów.")
    links = list(dict.fromkeys(int(n) for n in re.findall(r"\[\[(\d+)\]\]", text)))
    if any(n not in valid_ids for n in links):
        raise ValueError("Powiąż myśl tylko z istniejącymi, podanymi numerami wspomnień.")
    if require_links and valid_ids and not links:
        raise ValueError("Retrospekcja musi wskazać wspomnienia, które łączy, np. [[12]].")
    prose = re.sub(r"\[\[\d+\]\]", "", text)
    prose = " ".join(prose.split()).strip(" #")
    if len(prose) < 25:
        raise ValueError("Brakuje treści spostrzeżenia.")
    return prose, links


def read_reflection(text: str, valid_ids: set[int]) -> list[tuple[str, list[int]]]:
    if not isinstance(text, str) or len(text) > 4800:
        raise ValueError("Retrospekcja powinna mieć najwyżej 4800 znaków.")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not 1 <= len(paragraphs) <= 4:
        raise ValueError("Napisz 1–4 akapity, oddzielone pustą linią.")
    parsed = [read_note(p, valid_ids, require_links=True) for p in paragraphs]
    used: set[int] = set()
    for _, links in parsed:
        if used.intersection(links):
            raise ValueError("Jedno wspomnienie łącz tylko w jednym akapicie retrospekcji.")
        used.update(links)
    return parsed


class Memory:
    def __init__(self, budget: int = 8000):
        if not 600 <= budget <= 32000:
            raise ValueError("Budżet pamięci musi wynosić od 600 do 32000.")
        self.budget = budget
        self.nodes: list[MemoryNode] = []
        self.impressions: list[Impression] = []
        self.next_id = 1
        self.sleeps = self.forgotten = 0
        self.pressure = False
        self.last_sleep: dict = {}
        self.erased = False

    def erase(self) -> None:
        self.nodes.clear()
        self.impressions.clear()
        self.last_sleep.clear()
        self.next_id = 1
        self.sleeps = self.forgotten = 0
        self.pressure = False
        self.erased = True

    def _require_active(self) -> None:
        if self.erased:
            raise ValueError("Pamięć martwej istoty została usunięta.")

    @property
    def valid_ids(self) -> set[int]:
        return {n.id for n in self.nodes} | {i.id for i in self.impressions}

    def context(self) -> str:
        if self.erased:
            return ""
        parts = []
        for node in self.nodes:
            source = ("cudze świadectwo: " + ", ".join(node.origins.values())
                      if node.origins else "własne spostrzeżenie")
            if node.source == "observation":
                source = "ostatnia własna obserwacja; obecny stan może być inny"
            if node.source == "experience":
                source = "mój zamiar, przewidywanie i przebieg próby; wniosek nie jest przesądzony"
                if node.origins:
                    source += "; nawiązuje też do świadectwa: " + ", ".join(node.origins.values())
            if node.source == "spoken":
                source = "wypowiedziana przeze mnie myśl"
            if node.audience:
                source += "; wypowiedź do: " + ", ".join(node.audience.values())
            if node.utterance:
                source += "; " + dialogue_label(node.utterance)
            links = "; związane z " + ", ".join(f"[[{i}]]" for i in node.links) if node.links else ""
            parts.append(f"[[{node.id}]] {source}{links}\n{node.text}")
        if self.impressions:
            parts.append("ŚWIEŻE WRAŻENIA, JESZCZE NIE ZINTERPRETOWANE:")
            parts.extend(f"[[{i.id}]] {i.text}" for i in self.impressions)
        return "\n\n".join(parts)

    @property
    def used(self) -> int:
        return estimate_tokens(self.context())

    @property
    def ratio(self) -> float:
        return self.used / self.budget

    @property
    def needs_sleep(self) -> bool:
        return self.pressure or self.ratio >= 0.94

    def capacity(self) -> dict:
        return {"estimated_tokens": self.used, "budget_estimated_tokens": self.budget,
                "fill_percent": round(self.ratio * 100), "sleep_threshold_percent": 94,
                "sleep_needed": self.needs_sleep, "forgotten_items": self.forgotten,
                "sleeps": self.sleeps, "nodes": len(self.nodes),
                "estimator": "ceil(UTF-8 bytes / 3), not exact model tokens"}

    def observe(self, observation: dict, tick: int) -> None:
        """A bounded, sensory episode with a usable referent, not an omniscient map.

        Its text includes all target data and is charged to the ordinary budget.
        Reflection may link it, but cannot silently replace observed evidence.
        """
        self._require_active()
        identity = observation["id"]
        existing = next((n for n in self.nodes if n.observation and n.observation["id"] == identity), None)
        if existing and existing.observation == observation:
            return
        if existing:
            # An in-flight reflection may refer to this exact earlier view.
            # Retain its prose and ID; only the latest view is a navigation target.
            existing.observation = None
        label = ("jedzenie" if observation["kind"] == "food" else
                 ("martwą istotę " if observation.get("alive") is False else "istotę ") + observation.get("name", identity))
        text = (f"Ostatnio widziałam {label} (cel: {identity}) w miejscu "
                f"({observation['x']:.3f}, {observation['y']:.3f}), o promieniu {observation['radius']:.2f} m, "
                f"w chwili {tick}. {observation.get('appearance', '')} "
                "To zapamiętane spostrzeżenie; późniejszego stanu poza wzrokiem nie znam.")
        self.nodes.append(MemoryNode(self.next_id, tick, text, source="observation", observation=dict(observation)))
        self.next_id += 1
        self._trim()

    def target(self, identity: str) -> dict | None:
        return next((dict(n.observation) for n in self.nodes
                     if n.observation and n.observation["id"] == identity), None)

    def forget_target(self, identity: str) -> None:
        # Keep the experienced episode, but do not offer a consumed/disproved target.
        for node in self.nodes:
            if node.observation and node.observation["id"] == identity:
                node.observation = None
                node.text += " Później sprawdziłam: nie jest już dostępnym celem w tym miejscu."
        self._trim()

    def remember(self, tick: int, text: str, importance: float = 0.4, *, body: dict | None = None) -> Impression:
        """A small working buffer; physical telemetry is NOT durable knowledge."""
        self._require_active()
        item = Impression(self.next_id, tick, text[:500], importance, body)
        self.next_id += 1
        self.impressions.append(item)
        while (len(self.impressions) > 8 or
               estimate_tokens("\n".join(i.text for i in self.impressions)) > self.budget * 0.28):
            self.impressions.remove(min(self.impressions, key=lambda i: (i.importance, i.id)))
        self._trim()
        return item

    def related(self, cues: str, *, identities=(), limit=4) -> list[int]:
        """Cue/graph retrieval, not a generated conclusion or a truth score."""
        ignored = {"które", "który", "przed", "teraz", "swoje", "mojej", "jestem", "przez", "można"}
        def words(text):
            return {w[:6] for w in re.findall(r"\w+", text.casefold()) if len(w) >= 4 and w not in ignored}
        query = words(cues)
        identities = set(identities)
        scored = {}
        for n in self.nodes:
            score = len(query & words(n.text))
            if identities.intersection({*n.origins, *n.audience}):
                score += 6
            if n.observation and n.observation["id"] in identities:
                score += 3
            if score:
                scored[n.id] = score
        seeds = sorted(scored, key=lambda i: scored[i], reverse=True)[:limit]
        for node in self.nodes:
            if node.id in seeds:
                for linked in node.links:
                    scored[linked] = scored.get(linked, 0) + 2
            elif set(node.links).intersection(seeds):
                scored[node.id] = scored.get(node.id, 0) + 2
        return sorted(scored, key=lambda i: (scored[i], i), reverse=True)[:limit]

    def add_thought(self, text: str, tick: int, *, context_ids: set[int] | None = None) -> MemoryNode | None:
        self._require_active()
        if not text or text.strip() == "Bez nowego spostrzeżenia.":
            return None
        # A concurrent physical event may evict an impression used by a request.
        # Validate against what that request saw, without resurrecting old memory.
        consumed = self.valid_ids if context_ids is None else context_ids
        prose, refs = read_note(text, consumed)
        parents = [n for n in self.nodes if n.id in refs]
        origins = {key: value for n in parents for key, value in n.origins.items()}
        audience = {key: value for n in parents for key, value in n.audience.items()}
        for parent in parents:
            parent.strength = min(3.0, parent.strength + 0.12)
            parent.rehearsals += 1
        node = MemoryNode(self.next_id, tick, prose, [n.id for n in parents],
                          source="testimony" if origins else "insight", origins=origins, audience=audience)
        self.next_id += 1
        self.nodes.append(node)
        # The model has selected what matters from this transient stream.
        self.impressions = [i for i in self.impressions if i.id not in consumed]
        self._trim()
        return node

    def remember_story(self, tick: int, story: str, speaker_id: str,
                       speaker_name: str, *, heard: bool = True,
                       listener_id: str = "", listener_name: str = "", utterance: dict | None = None) -> MemoryNode:
        self._require_active()
        story = validate_story(story, reply=bool(utterance and utterance.get("reply_to")))
        partner = speaker_id if heard else listener_id
        previous = [n.id for n in self.nodes if partner in n.origins or partner in n.audience][-2:]
        node = MemoryNode(self.next_id, tick, story, previous, 1.25,
                          "testimony" if heard else "spoken",
                          {speaker_id: speaker_name} if heard else {},
                          audience={listener_id: listener_name} if not heard and listener_id else {},
                          utterance=dict(utterance) if utterance else None)
        self.next_id += 1
        self.nodes.append(node)
        self._trim()
        return node

    def _trim(self) -> None:
        while self.used > self.budget and self.impressions:
            self.impressions.remove(min(self.impressions, key=lambda i: (i.importance, i.id)))
        while self.used > self.budget and self.nodes:
            self.pressure = True
            # Meaningful, recalled and connected nodes resist emergency eviction.
            degree = {n.id: sum(n.id in other.links for other in self.nodes) for n in self.nodes}
            weakest = min(self.nodes, key=lambda n: (n.strength + min(1, degree[n.id] * 0.15), n.tick))
            self.nodes.remove(weakest)
            for node in self.nodes:
                node.links = [i for i in node.links if i != weakest.id]
            self.forgotten += 1

    def consolidate(self, reflection: str, *, context_ids: set[int] | None = None) -> dict:
        self._require_active()
        consumed = self.valid_ids if context_ids is None else context_ids
        parsed = read_reflection(reflection, consumed)
        before, forgotten_before = self.used, self.forgotten
        old = {n.id: n for n in self.nodes}
        recent_trials = {n.id for n in self.nodes if n.experience and n.experience["state"] == "reviewed"}
        recent_trials = set(sorted(recent_trials)[-4:])
        protected = {n.id for n in self.nodes if n.source == "observation" or
                     (n.experience and (n.experience["state"] != "reviewed" or n.id in recent_trials)) or
                     (n.utterance and n.utterance.get("state") in ("new", "considered", "waiting"))}
        redirects: dict[int, int] = {}
        strengthened = []
        merged = 0
        for prose, refs in parsed:
            parents = [old[i] for i in refs if i in old and i not in protected]
            anchor = max(parents, key=lambda n: n.strength) if parents else None
            node_id = anchor.id if anchor else self.next_id
            if anchor is None:
                self.next_id += 1
            evidence = [old[i] for i in refs if i in old]
            origins = {key: value for n in evidence for key, value in n.origins.items()}
            audience = {key: value for n in evidence for key, value in n.audience.items()}
            links = list(dict.fromkeys([i for n in parents for i in n.links if i not in refs]
                                      + [i for i in refs if i in protected]))
            node = MemoryNode(node_id, max((n.tick for n in parents), default=0), prose, links,
                              min(3, max((n.strength for n in parents), default=1) + 0.2),
                              "testimony" if origins else "insight", origins,
                              max((n.rehearsals for n in parents), default=0) + 1, audience)
            for parent in parents:
                self.nodes.remove(parent)
                redirects[parent.id] = node_id
            self.nodes.append(node)
            strengthened.append(node_id)
            merged += max(0, len(parents) - 1)
        weakened = []
        for node in self.nodes:
            node.links = list(dict.fromkeys(redirects.get(i, i) for i in node.links
                                           if redirects.get(i, i) != node.id))
            if node.id not in strengthened and node.id in consumed:
                node.strength = max(0.2, node.strength * 0.95)
                weakened.append(node.id)
        self.impressions = [i for i in self.impressions if i.id not in consumed]
        self._trim()
        self.sleeps += 1
        self.pressure = False
        self.last_sleep = {"before": before, "after": self.used, "reinforced": strengthened,
                           "weakened": weakened, "merged": merged,
                           "forgotten": self.forgotten - forgotten_before,
                           "reflection": "\n\n".join(prose for prose, _ in parsed)}
        return self.last_sleep

    def to_dict(self) -> dict:
        return {"format": 3, "budget": self.budget, "nodes": [n.to_dict() for n in self.nodes],
                "impressions": [asdict(i) for i in self.impressions], "next_id": self.next_id,
                "sleeps": self.sleeps, "forgotten": self.forgotten, "pressure": self.pressure,
                "last_sleep": self.last_sleep, "erased": self.erased}

    @classmethod
    def from_dict(cls, data: dict) -> Memory:
        memory = cls(data["budget"])
        if data.get("erased"):
            memory.erase()
            return memory
        if data.get("format") == 3:
            memory.nodes = [MemoryNode(**n) for n in data["nodes"]]
            memory.impressions = [Impression(**i) for i in data.get("impressions", [])]
            memory.next_id = data["next_id"]
        else:
            # Migrate old lessons and stories, not hundreds of deterministic map cells.
            context = data.get("context", {})
            entries = ([{"text": context["summary"]}] if context.get("summary") else [])
            entries += context.get("knowledge", [])
            entries += [e for e in context.get("episodes", []) if e.get("source") in ("testimony", "spoken")]
            for entry in entries:
                origins = {entry["speaker_id"]: entry.get("speaker_name", entry["speaker_id"])} if entry.get("speaker_id") else {
                    key: key for key in entry.get("speaker_ids", [])}
                memory.nodes.append(MemoryNode(memory.next_id, entry.get("tick", 0), entry["text"],
                                               source="testimony" if origins else "insight", origins=origins))
                memory.next_id += 1
        for key in ("sleeps", "forgotten", "pressure", "last_sleep"):
            setattr(memory, key, data.get(key, getattr(memory, key)))
        valid = {n.id for n in memory.nodes}
        for node in memory.nodes:
            node.links = [i for i in node.links if i in valid and i != node.id]
        memory._trim()
        return memory
