"""Intentions and their measured outcomes live in the ordinary, bounded memory."""
from __future__ import annotations

from .memory import MemoryNode


class Experience:
    def __init__(self, owner):
        self.owner = owner

    def rows(self, *states):
        return [n for n in self.owner.memory.nodes if n.experience and
                (not states or n.experience["state"] in states)]

    def reading(self):
        a = self.owner
        return {"energy": round(a.energy, 3), "time": round(a.lifetime_seconds, 3),
                "fatigue": round(a.fatigue, 2), "position": list(a.position),
                "heading": float(a.facing), "speed": round(a.movement_speed, 3)}

    def _write(self, node):
        e = node.experience
        e["outcomes"] = e["outcomes"][-8:]
        status = {"active": "realizuję ten zamiar", "queued": "zamiar czeka na wykonanie",
                  "ready": "próba zakończona; wynik wymaga interpretacji",
                  "reviewed": "próba została rozważona"}[e["state"]]
        if e["state"] == "active" and e["baseline"] is None:
            status = "zamiar przyjęty; próba jeszcze się nie rozpoczęła"
        node.text = (f"Mój cel: {e['goal']}. Mój zamiar: {e['intent']}. "
                     f"Moje przewidywanie przed próbą: {e['expectation'] or 'nie zapisałam przewidywania'}. "
                     f"Stan: {status}.")
        b = e["baseline"]
        if b:
            node.text += (f" Przed próbą: czas {b['time']:.1f} s, energia {b['energy']:.2f}, "
                          f"zmęczenie {b['fatigue']:.1f}, położenie {b['position']}, "
                          f"kierunek oczu {b['heading']:.1f}°, dostępna szybkość chodu {b['speed']:.2f} m/s.")
        if e["outcomes"]:
            node.text += " Rzeczywiście zaobserwowane wyniki: " + " ".join(e["outcomes"])
        self.owner.memory._trim()

    def begin(self, plan, tick):
        if not plan.actions:
            return
        if plan.control == "replace":
            self.interrupt("Zmieniam poprzedni zamiar: " + plan.intent)
        # Replacing the queued part must not attribute the current motor's
        # result to a new intention that has not started yet.
        for old in self.rows("queued"):
            self._finish(old, "Zmieniłam kolejkę przed wykonaniem tego zamiaru.")
        if plan.control == "queue":
            for old in self.rows("active"):
                old.experience["remaining"] = 1
                old.experience["outcomes"].append("Zmieniłam dalszą kolejkę; kończę tylko rozpoczętą czynność.")
                self._write(old)
        memory = self.owner.memory
        refs = memory.related(plan.goal + " " + plan.intent + " " + plan.expectation, limit=3)
        origins = {key: value for n in memory.nodes if n.id in refs for key, value in n.origins.items()}
        node = MemoryNode(memory.next_id, tick, "", refs, source="experience", origins=origins, experience={
            "state": "queued" if self.owner.motor is not None else "active",
            "goal": plan.goal, "intent": plan.intent, "expectation": plan.expectation,
            "remaining": len(plan.actions), "baseline": None, "outcomes": [],
        })
        memory.next_id += 1
        memory.nodes.append(node)
        self._write(node)

    def start(self):
        active = self.rows("active")
        if not active:
            active = self.rows("queued")[:1]
        for node in active:
            e = node.experience
            e["state"] = "active"
            if e["baseline"] is None:
                e["baseline"] = self.reading()
            self._write(node)

    def outcome(self, text, *, failed=False):
        for node in self.rows("active"):
            e = node.experience
            # Both the command count and result text are bounded.
            e["outcomes"].append(text[:450])
            e["remaining"] -= 1
            if failed or e["remaining"] <= 0:
                self._finish(node)
            else:
                self._write(node)

    def _finish(self, node, reason=""):
        e = node.experience
        if reason:
            e["outcomes"].append(reason[:450])
        before = e["baseline"]
        if before:
            after = self.reading()
            e["outcomes"].append(
                f"W czasie próby upłynęło {after['time'] - before['time']:.1f} s; "
                f"energia {before['energy']:.2f} → {after['energy']:.2f}; "
                f"zmęczenie {before['fatigue']:.1f} → {after['fatigue']:.1f}; "
                f"dostępna szybkość chodu {before['speed']:.2f} → {after['speed']:.2f} m/s. "
                f"Teraz położenie {after['position']}, kierunek oczu {after['heading']:.1f}°. "
                "To łączna zmiana podczas próby, również z równoległą pracą umysłu.")
        e["outcomes"] = e["outcomes"][-8:]
        e["state"] = "ready"
        self._write(node)

    def interrupt(self, reason):
        for node in self.rows("active", "queued"):
            self._finish(node, reason)

    def skip_last_command(self, reason):
        rows = self.rows("queued") or self.rows("active")
        if rows:
            node = rows[-1]
            node.experience["remaining"] -= 1
            node.experience["outcomes"].append(reason)
            if node.experience["remaining"] <= 0:
                self._finish(node)
            else:
                self._write(node)

    def spoke(self, message_id, peer_id):
        for node in self.rows("active"):
            node.experience["message_id"] = message_id
            node.experience["peer_id"] = peer_id

    def heard_reply(self, reply_to, heard):
        if not reply_to:
            return
        for node in self.rows("ready", "reviewed"):
            if node.experience.get("message_id") == reply_to:
                node.experience["outcomes"].append(
                    "Później usłyszałam odpowiedź: „" + heard.text[:450] + "”. To cudza relacja, nie dowód jej treści.")
                node.experience["state"] = "ready"
                node.origins.update(heard.origins)
                if heard.id not in node.links:
                    node.links.append(heard.id)
                self._write(node)

    def recognize_dead(self, peer_id, name):
        for node in self.rows("ready", "reviewed"):
            e = node.experience
            if e.get("peer_id") == peer_id and not e.get("peer_dead"):
                e["peer_dead"] = True
                e["outcomes"].append(f"Później zobaczyłam: martwa istota {name}; nie może odpowiedzieć. Przyczyny śmierci nie znam.")
                e["state"] = "ready"
                self._write(node)

    def reviewed(self, thought_node, request_context):
        if thought_node is None:
            return
        # Only explicitly cited episodes whose result was already in the
        # snapshot can be reviewed. An in-flight motor result needs a new look.
        expected = {item["id"]: item["text"] for item in request_context}
        for node in self.rows("ready"):
            if node.id in thought_node.links and expected.get(node.id) == node.text:
                node.experience["state"] = "reviewed"
                self._write(node)

    def snapshot(self):
        return [{"id": n.id, "text": n.text, "state": n.experience["state"]}
                for n in self.rows("active", "queued", "ready")]
