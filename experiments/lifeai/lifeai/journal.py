"""Observer-only history. Never part of an agent's memory or LLM context."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class ObserverJournal:
    def __init__(self, *, session_id: str | None = None,
                 events: list[dict] | None = None, history_complete: bool = True):
        self.session_id = session_id or uuid4().hex
        self.events = json.loads(json.dumps(events or [], ensure_ascii=False))
        self.history_complete = history_complete
        self.sequence = max((e.get("sequence", 0) for e in self.events), default=0)
        self.path: Path | None = None
        self.directory: Path | None = None
        self.error = ""
        self._written = 0

    def record(self, event: dict) -> dict:
        self.sequence += 1
        record = json.loads(json.dumps({
            **event, "sequence": self.sequence,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False))
        self.events.append(record)
        self.flush()
        return record

    def attach(self, directory: Path, state: dict) -> Path:
        if self.path is not None:
            return self.path
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        path = directory / f"{stamp}_{self.session_id}_{uuid4().hex[:8]}.jsonl"
        header = {"type": "session_snapshot", "format": 1, "session_id": self.session_id,
                  "history_complete": self.history_complete, "state": state}
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(header, ensure_ascii=False) + "\n")
        self.path, self.directory = path, directory
        self.flush()
        if self.error:
            raise OSError(self.error)
        return path

    def flush(self) -> None:
        if self.path is None or self._written == len(self.events):
            return
        try:
            # Main-thread writes; each line is closed/flushed immediately. A later
            # session gets a new file, including when resuming an older checkpoint.
            with self.path.open("a", encoding="utf-8") as stream:
                for record in self.events[self._written:]:
                    stream.write(json.dumps({"type": "event", **record}, ensure_ascii=False) + "\n")
                    stream.flush()
                    self._written += 1
            self.error = ""
        except OSError as exc:
            # Keep the complete in-memory history and retry on the next event/save.
            self.error = str(exc)

    def to_dict(self) -> dict:
        return {"session_id": self.session_id, "history_complete": self.history_complete,
                "events": self.events}

    @classmethod
    def from_session(cls, data: dict) -> ObserverJournal:
        if "observer_journal" in data:
            return cls(**data["observer_journal"])
        # Old snapshots only retained the last 100 events and erased them on death.
        # Their missing chronology cannot be recovered or advertised as complete.
        events = []
        for agent in data["agents"]:
            fallback = data if agent["id"] == data["selected_agent"] else {}
            saved = data.get("controllers", {}).get(agent["id"], fallback)
            events.extend({**event, "agent_id": agent["id"], "agent_name": agent["name"],
                           "legacy": True} for event in saved.get("events", []))
        events.sort(key=lambda e: e.get("tick", 0))
        for sequence, event in enumerate(events, 1):
            event["sequence"] = sequence
        return cls(events=events, history_complete=False)
