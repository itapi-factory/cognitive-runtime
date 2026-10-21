from __future__ import annotations

import json
import threading
import time
from collections import deque
from concurrent.futures import Future
from pathlib import Path

from .agent import Agent
from .brain import Brain, BrainError, LocalLLM, PlanValidationError
from .config import Settings
from .conversation import RepeatedSpeech, dialogue_label, is_repetition, validate_story
from .energy import ENERGY
from .journal import ObserverJournal
from .memory import compact_json
from .world import Heading, Tile, World


class Simulation:
    """Main-thread state machine; background threads only see immutable snapshots."""

    def __init__(self, settings: Settings, brain: Brain | None = None, *,
                 world: World | None = None, agent: Agent | None = None,
                 journal: ObserverJournal | None = None, record_birth: bool = True):
        self.settings = settings
        self.brain = brain if brain is not None else LocalLLM(settings)
        self.world = world if world is not None else World(seed=settings.seed)
        self.agent = agent if agent is not None else Agent(
            "ada-01", (self.world.width / 2, self.world.height / 2),
            memory_budget=settings.memory_budget, vision_range=settings.vision_range,
        )
        if self.agent.id not in self.world.entities:
            self.world.add_agent(self.agent)
        self.controllers: dict[str, Simulation] = {self.agent.id: self}
        self.phase = "observe"
        self._paused = False
        self._last_update_at: float | None = None
        self._terminated = threading.Event()
        self.pending: Future | None = None
        self.pending_kind = ""
        self.request_started = 0.0
        self.next_action_at = 0.0
        self.action_delay = 0.65
        self._motor_dt = 0.0
        self._last_motor_log = 0.0
        self.error = ""
        self.retry_kind = ""
        self.retry_count = 0
        self.retry_at = 0.0
        self.retry_is_validation = False
        self.plan_feedback = ""
        self.sleep_requested = False
        self.sleep_reason = ""
        self.cycles = 0
        self.journal = journal if journal is not None else ObserverJournal()
        self.events: deque[dict] = deque(e for e in self.journal.events if e["agent_id"] == self.agent.id)
        self.last_prompt: dict = {}
        self._replan_after_request = False
        self._request_memory_ids: set[int] | None = None
        self._request_experiences: list[dict] = []
        self._request_activity_revision: int | None = None
        self._dialogue_interrupt = False
        self._speech_reply_to: str | None = None
        self._seen_death_revision = 0
        self.next_thought_lifetime = 0.0
        self.conversations = 0
        self.closed = False
        if record_birth:
            self.event("Narodziny", f"{self.agent.name} otwiera oczy. Decyzje podejmuje lokalny LLM.", "system")
        if world is None:
            for _ in range(settings.agent_count - 1):
                self.add_companion()

    def add_companion(self, *, near: Agent | None = None, brain: Brain | None = None) -> Simulation:
        if len(self.controllers) >= 8:
            raise ValueError("Na tej arenie może żyć maksymalnie 8 istot.")
        near = near or self.agent
        x, y = near.position
        dx, dy = near.facing.vector
        preferred = [(x + 2 * dx - dy, y + 2 * dy + dx),
                     (x + 2 * dx + dy, y + 2 * dy - dx), near.mouth_position]
        other_spots = [Heading(angle).ahead(near.position, distance)
                       for distance in (1.5, 2.5, 4, 6, 9) for angle in range(0, 360, 15)]
        pos = next((p for p in preferred + other_spots
                    if self.world.tile(p) == Tile.EMPTY and self.world.walkable(p)), None)
        if pos is None:
            raise ValueError("Brak miejsca dla kolejnej istoty.")
        index = len(self.controllers)
        name = ("Ada", "Bruno", "Celina", "Dorian", "Emilia", "Feliks", "Gaja", "Hugo")[index]
        companion = Agent(f"{name.lower()}-{index + 1:02}", pos,
                          Heading(near.facing + 180), memory_budget=self.settings.memory_budget,
                          vision_range=self.settings.vision_range, name=name)
        controller = Simulation(self.settings, brain, world=self.world, agent=companion, journal=self.journal)
        controller.controllers = self.controllers
        controller._paused = self.paused
        controller.action_delay = self.action_delay
        self.controllers[companion.id] = controller
        return controller

    def _listener(self) -> Simulation | None:
        listener = self.controllers.get(self.agent.talk_target)
        if (listener and listener.agent.alive and listener.phase != "sleeping"
                and self._speech_target(listener.agent.id) is not None):
            return listener
        return None

    def _speech_target(self, identity: str) -> Agent | None:
        target = self.world.entities.get(identity)
        if target is None or not target.alive or not (self.world.can_address(self.agent, target) or
                (self.agent.dialogue.recent_contact(identity) and self.world.can_hear(self.agent, target))):
            return None
        if target.alive:
            controller = self.controllers.get(identity)
            if controller is None or controller.phase == "sleeping":
                return None
        return target

    def _refresh_senses(self, *, remember=False) -> None:
        self.agent.look(self.world, remember=remember)
        if self._seen_death_revision == self.agent.death_notice_revision:
            return
        self._seen_death_revision = self.agent.death_notice_revision
        self.agent.last_result = self.agent.death_notice
        self.event("Rozpoznana śmierć", self.agent.death_notice, "observation")
        self.next_thought_lifetime = self.agent.lifetime_seconds
        if self.pending_kind == "plan":
            self._replan_after_request = True
        target = self.agent.known_target(self.agent.talk_target)
        if target and target.get("alive") is False:
            if any(c["action"] == "talk" for c in self.agent.plan):
                self.agent.experience.skip_last_command("Nie wykonam zaplanowanej rozmowy: " + self.agent.death_notice)
            self.agent.plan = deque(c for c in self.agent.plan if c["action"] != "talk")
            # Only a conversational wait ends here; walking/eating remain autonomous.
            if self.agent.motor and self.agent.motor.action == "wait":
                self._stop_body(self.agent.death_notice)
            if self.phase == "retrying" and self.retry_kind == "talk":
                self.error = self.retry_kind = ""
                self.retry_count = 0
                self.phase = "observe"

    def _contact_failure(self) -> str:
        target = self.agent.known_target(self.agent.talk_target)
        if target and target.get("alive") is False:
            return f"{target.get('name', self.agent.talk_target)} to martwa istota. Rozmowa jest zakończona; nie oczekuję odpowiedzi."
        return "Nie udało mi się utrzymać kontaktu z rozmówcą."

    def _snapshot(self) -> dict:
        self._refresh_senses(remember=True)
        snapshot = self.agent.snapshot(self.settings.max_plan)
        snapshot["conversation"]["partners"] = [
            p for p in snapshot["conversation"]["partners"]
            if self._speech_target(p["id"]) is not None
        ]
        return snapshot

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        changed = self._paused != bool(value)
        for controller in self.controllers.values():
            controller._paused = bool(value)
            # Time spent paused must never be billed on resume.
            controller._last_update_at = None
            controller._motor_dt = 0.0
        if changed:
            self.event("Pauza" if value else "Wznowienie", "Obserwator zatrzymał czas." if value else
                       "Obserwator wznowił czas.", "system", paused=bool(value))

    @property
    def energy_per_second(self) -> float:
        return ENERGY.per_second(self.phase) if self.agent.alive and not self.paused else 0.0

    def _handle_death(self) -> None:
        if self.phase == "dead":
            return
        self.agent.die(self.agent.death_reason or "Brak energii.")
        self.world.leave_corpse(self.agent)
        self._terminated.set()
        if self.pending:
            self.pending.cancel()
        self.pending = None
        self.pending_kind = self.retry_kind = self.error = self.sleep_reason = ""
        self.sleep_requested = False
        self.retry_count = 0
        self.retry_at = 0.0
        self.retry_is_validation = False
        self.plan_feedback = ""
        self.last_prompt.clear()
        self._request_memory_ids = None
        self._request_experiences.clear()
        self._request_activity_revision = None
        self._dialogue_interrupt = False
        self._speech_reply_to = None
        # The living mind is erased; the separate observer journal survives.
        forget = getattr(self.brain, "forget", None)
        if forget:
            forget()
        self.phase = "dead"
        if not any(e["kind"] == "death" for e in self.events):
            self.event("Śmierć", "Energia spadła do zera. Cała pamięć istoty została usunięta.", "death",
                       reason=self.agent.death_reason)

    def body_state(self) -> dict:
        return {"position": list(self.agent.position), "facing": self.agent.facing.name, "heading": float(self.agent.facing),
                "energy": round(self.agent.energy, 6), "fatigue": round(self.agent.fatigue, 3),
                "age": self.agent.age, "lifetime_seconds": round(self.agent.lifetime_seconds, 6),
                "alive": self.agent.alive, "physical_activity": self.agent.activity_snapshot()}

    def event(self, title: str, text: str, kind: str = "action", **details) -> None:
        # Observer-only telemetry: never available to the creature as extra memory.
        record = self.journal.record({"tick": self.world.tick, "title": title, "text": text, "kind": kind,
                                      "agent_id": self.agent.id, "agent_name": self.agent.name,
                                      "body": self.body_state(), "phase": self.phase, **details})
        self.events.append(record)

    def enable_journal(self, directory: Path) -> Path:
        return self.journal.attach(directory, {
            "world": self.world.to_dict(),
            "agents": [c.agent.to_dict() for c in self.controllers.values()],
        })

    def _submit(self, kind: str) -> None:
        if self.pending is not None or self.closed:
            return
        if kind == "sleep":
            self._stop_body("Zatrzymuję ciało przed snem.")
        if kind == "talk":
            self._refresh_senses()
        target = self._speech_target(self.agent.talk_target) if kind == "talk" else None
        if kind == "talk" and target is None:
            self._talk_failed(self._contact_failure())
            return
        if kind == "talk":
            other = self.controllers.get(target.id)
            if (other and other.pending is not None and other.pending_kind == "talk"
                    and other.agent.talk_target == self.agent.id):
                # Give a simultaneous speaker the floor; preserve our queued intent.
                return False
            if self.agent.dialogue.waiting(target.id) and not self.agent.dialogue.incoming(target.id):
                self._defer_repeated_turn()
                return
        if kind in ("talk", "sleep"):
            self.agent.experience.start()
        cost = {"sleep": ENERGY.sleep_start, "talk": ENERGY.speech_start}.get(kind, ENERGY.planning)
        self.event("Praca umysłu", f"Rozpoczynam etap: {kind}.", "cognition", operation=kind, startup_cost=cost)
        self.agent.sense_body(self.world.tick, "Przed pracą umysłu.")
        if not self.agent.spend_energy(cost, "Brak energii na rozpoczęcie pracy umysłu."):
            self._handle_death()
            return
        snapshot = self._snapshot()
        if kind == "plan" and self.plan_feedback:
            snapshot["validation_feedback"] = (
                "Poprzednia decyzja została odrzucona: " + self.plan_feedback +
                "\nTo opis poprzedniej próby. Teraz korzystaj z odświeżonych zmysłów, listy rozmówców "
                "i stanu ciała powyżej. Dotychczasowy cel możesz ponownie rozważyć.")
        if kind == "sleep":
            snapshot["sleep_reason"] = self.sleep_reason
        elif kind == "talk":
            # Only a public identity crosses this boundary, never the listener's mind.
            snapshot["listener"] = {"id": target.id, "name": target.name}
            snapshot["speech_intent"] = self.agent.speech_intent
            snapshot["dialogue"] = self.agent.dialogue.snapshot(target.id)
            incoming = self.agent.dialogue.incoming(target.id)
            snapshot["reply_to"] = (next((n for n in snapshot["dialogue"]["incoming"]
                                          if n["memory_id"] == incoming.id), None) if incoming else None)
            self._speech_reply_to = incoming.utterance["id"] if incoming else ""
        if kind in ("plan", "sleep"):
            self._request_memory_ids = set(snapshot["memory_ids"])
            self._request_experiences = snapshot.get("experience", [])
        if kind == "plan":
            self._replan_after_request = False
            self._dialogue_interrupt = False
            self._request_activity_revision = self.agent.activity_revision
        # JSON round-trip guarantees the worker cannot mutate live state.
        snapshot = json.loads(compact_json(snapshot))
        self.last_prompt = json.loads(compact_json(snapshot))
        self.event("Kontekst LLM", f"Obserwacje i pamięć przed etapem: {kind}.", "context",
                   operation=kind, context=snapshot)
        future = Future()
        self.pending, self.pending_kind = future, kind
        self.request_started = time.monotonic()
        self.phase = {"sleep": "sleeping", "talk": "talking"}.get(kind, "thinking")

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                if self._terminated.is_set():
                    future.set_result(None)
                    return
                operation = {"sleep": self.brain.reflect, "plan": self.brain.plan}.get(kind)
                if kind == "talk":
                    operation = self.brain.narrate
                result = operation(snapshot)
                future.set_result(None if self._terminated.is_set() else result)
            except Exception as exc:
                if self._terminated.is_set():
                    future.set_result(None)
                else:
                    future.set_exception(exc)
            finally:
                snapshot.clear()

        # A stalled network request must never keep the Pygame process alive on exit.
        threading.Thread(target=run, name=f"lifeai-{kind}", daemon=True).start()

    def _receive(self, now: float) -> None:
        if not self.agent.alive:
            self._handle_death()
            return
        self._refresh_senses()
        future, kind = self.pending, self.pending_kind
        self.pending = None
        self.pending_kind = ""
        # Includes validation feedback if the model had to correct its response.
        self.last_prompt = getattr(self.brain, "last_snapshot", self.last_prompt)
        if kind == "talk" and self._speech_target(self.agent.talk_target) is None:
            self._speech_reply_to = None
            self._talk_failed(self._contact_failure(), charge=False)
            return
        try:
            result = future.result()
            # Do not mutate the sleep evidence before applying its reflection.
            if kind == "talk":
                self.agent.sense_body(self.world.tick, "Po pracy umysłu.")
            if kind == "sleep":
                self.event("Próba konsolidacji", "LLM zakończył retrospekcję; ciało opłaca porządkowanie pamięci.",
                           "sleep_pending", proposed_reflection=result,
                           consolidation_cost=ENERGY.consolidation_cost(self.agent.memory.used),
                           memory_used=self.agent.memory.used)
                report = self.agent.wake(result, self.world, context_ids=self._request_memory_ids)
                if report is None:
                    self._handle_death()
                    return
                for node in list(self.agent.memory.nodes):
                    if node.id in report["reinforced"]:
                        self.agent.experience.reviewed(node, self._request_experiences)
                self.event(
                    "Retrospekcja",
                    f"{report['before']} → {report['after']} szac. tokenów. "
                    + report["reflection"], "sleep", report=report,
                )
                self.phase = "waking"
                self.sleep_requested = False
            elif kind == "talk":
                self._deliver_story(result)
                self._speech_reply_to = None
                if not self.agent.alive:
                    return
            else:
                self.cycles += 1
                self.plan_feedback = ""
                # A reflection remains useful even if an external displacement
                # made its associated movement plan obsolete.
                node = self.agent.memory.add_thought(result.thought, self.world.tick,
                                                     context_ids=self._request_memory_ids)
                self.agent.experience.reviewed(node, self._request_experiences)
                stale = (self._replan_after_request or self._dialogue_interrupt or self.sleep_requested or
                         (self._request_activity_revision is not None and
                          self._request_activity_revision != self.agent.activity_revision))
                reason = ("Usłyszałam nową wypowiedź, której nie było w analizowanym kontekście."
                          if self._dialogue_interrupt else
                          "Po rozpoczęciu analizy zmieniła się czynność lub dostrzegłam śmierć innej istoty."
                          if stale else "")
                if not stale:
                    self._apply_decision(result)
                    self.agent.dialogue.reviewed(self._request_memory_ids or set())
                self.event("Decyzja LLM", result.intent, "plan", goal=result.goal, actions=result.actions,
                           thought=result.thought, listener_id=result.listener_id,
                           speech_intent=result.speech_intent, control=result.control, applied=not stale,
                           expectation=result.expectation,
                           decision_note=reason, request_activity_revision=self._request_activity_revision,
                           current_activity_revision=self.agent.activity_revision, thought_saved=node is not None)
                self._replan_after_request = False
                self._dialogue_interrupt = False
                self._request_activity_revision = None
                self.agent.sense_body(self.world.tick, "Po pracy umysłu.")
                self.phase = "acting" if self.agent.motor or self.agent.plan else "observe"
                self.next_thought_lifetime = (self.agent.lifetime_seconds if stale else
                                             self.agent.lifetime_seconds + self.settings.thinking_interval)
            self.error = ""
            self.retry_count = 0
            self.retry_is_validation = False
            if kind != "plan" or (not stale and result.control == "replace"):
                self.next_action_at = now + self.action_delay
        except RepeatedSpeech as exc:
            self._speech_reply_to = None
            self._talk_failed(str(exc), charge=False)
            self.next_thought_lifetime = self.agent.lifetime_seconds
        except Exception as exc:
            self.error = str(exc)[:1200]
            self.retry_kind = kind
            validation = isinstance(exc, PlanValidationError)
            self.retry_count = self.retry_count + 1 if validation == self.retry_is_validation else 1
            self.retry_is_validation = validation
            if validation:
                # A rejected intention is not an API outage. Preserve the reason
                # across new snapshots, instead of asking the same question anew.
                self.plan_feedback = self.error
                node = self.agent.memory.add_thought(exc.thought, self.world.tick,
                                                     context_ids=self._request_memory_ids)
                self.agent.sense_body(self.world.tick, "Po analizie; odrzucony plan nie został wykonany.")
                self.event("Odrzucony plan", self.error, "plan_rejected", rejected_plan=exc.rejected_plan,
                           thought=exc.thought, thought_saved=node is not None)
            delay = .1 if validation else min(30.0, 2 ** min(self.retry_count - 1, 5))
            self.retry_at = now + delay
            self.phase = "retrying"
            self.event("Korekta planu" if validation else "Ponawianie LLM",
                       f"{self.error} Ponowię za {delay:g} s.", "error", error_type="plan" if validation else "request",
                       operation=kind, retry_count=self.retry_count, retry_delay=delay)

    def _stop_body(self, reason: str) -> None:
        command = dict(self.agent.motor.command) if self.agent.motor else None
        had_plan = bool(self.agent.plan)
        if command or had_plan:
            self.agent.cancel_activity(reason)
            if self.agent.alive:
                self.agent.last_result = reason
                self.agent.memory.remember(self.world.tick, reason, .7)
            self.event("Przerwane polecenie", reason, "motor_cancelled", command=command)

    def _apply_decision(self, plan) -> None:
        if plan.control == "continue":
            return
        if plan.control == "stop":
            self._stop_body("Świadomie zatrzymuję ciało: " + plan.intent)
            self.agent.goal, self.agent.intent = plan.goal, plan.intent
        elif plan.control == "replace":
            self._stop_body("Zmieniam zamiar podczas działania: " + plan.intent)
            self.agent.accept_plan(plan, self.world.tick, remember_thought=False)
        elif plan.control == "queue":
            if self.agent.motor is None:
                raise BrainError("Nie można zaplanować kolejki po nieistniejącej czynności.")
            self.agent.accept_plan(plan, self.world.tick, remember_thought=False)
        else:
            raise BrainError("Nieznany sposób zmiany aktywności ciała.")

    def _talk_failed(self, message: str, *, charge: bool = True, story: str = "") -> None:
        self.agent.experience.outcome(message, failed=True)
        self.agent.plan.clear()
        self.error, self.retry_kind = "", ""
        self.retry_count, self.retry_is_validation = 0, False
        if charge and not self.agent.spend_energy(ENERGY.action, "Brak energii na próbę rozmowy."):
            self._handle_death()
            return
        self.agent.age += 1
        self.world.advance()
        self.agent.last_result = message
        self.agent.memory.remember(self.world.tick, message, 0.6)
        self.event("Rozmowa nieudana", (story + "\n\n" if story else "") + message, "talk",
                   delivered=False, listener_id=self.agent.talk_target, spoken_text=story)
        self.phase = "observe"
        self.next_thought_lifetime = self.agent.lifetime_seconds

    def _defer_repeated_turn(self) -> None:
        self.agent.experience.outcome("Nie rozpoczęłam kolejnej wypowiedzi; poprzednia nadal czeka na reakcję.", failed=True)
        self.agent.plan.clear()
        self.error, self.retry_kind = "", ""
        self.retry_count, self.retry_is_validation = 0, False
        self.agent.last_result = "Moja ostatnia wypowiedź czeka na reakcję; nie powtarzam jej teraz."
        self.event("Czekam na reakcję", self.agent.last_result, "dialogue")
        self.phase = "acting" if self.agent.motor else "observe"
        self.next_thought_lifetime = self.agent.lifetime_seconds + self.settings.thinking_interval

    def _deliver_story(self, value: str) -> None:
        self._refresh_senses()
        target = self._speech_target(self.agent.talk_target)
        if target is None:
            self._talk_failed(self._contact_failure(), charge=False)
            return
        incoming = self.agent.dialogue.incoming(self.agent.talk_target)
        reply_to = self._speech_reply_to
        if reply_to is None:  # direct delivery, without a narration worker
            reply_to = incoming.utterance["id"] if incoming else ""
        if incoming and incoming.utterance["id"] != reply_to:
            self._talk_failed("Usłyszałam nową kwestię podczas przygotowania wypowiedzi; najpierw ją rozważę.", charge=False)
            return
        if self.agent.dialogue.waiting(self.agent.talk_target) and not incoming:
            self._defer_repeated_turn()
            return
        story = validate_story(value, reply=bool(reply_to))
        previous = [n for n in self.agent.dialogue.rows(self.agent.talk_target)
                    if n.utterance["direction"] == "sent"][-3:]
        if (not reply_to or len(story.split()) >= 8) and any(is_repetition(story, n.text) for n in previous):
            self._talk_failed("Pominęłam powtórzenie własnej wcześniejszej wypowiedzi.", charge=False)
            return
        target = self._speech_target(self.agent.talk_target)
        listener = self._listener()
        self.event("Próba wypowiedzi", story, "talk_pending", speaker_id=self.agent.id,
                   listener_id=self.agent.talk_target, speech_cost=ENERGY.speech_cost(story))
        if target is None:
            self._talk_failed("Nie udało mi się utrzymać kontaktu z rozmówcą.")
            return
        if not self.agent.spend_energy(ENERGY.speech_cost(story), "Brak energii na wypowiedzenie opowieści."):
            self._handle_death()
            return
        if not listener.agent.spend_energy(ENERGY.listening_cost(story), "Brak energii na wysłuchanie opowieści."):
            listener._handle_death()
            self._talk_failed("Rozmowa urwała się; nie otrzymałam odpowiedzi.", charge=False)
            return
        self.agent.age += 1
        self.world.advance()
        # Speech text lives only in bounded memory. IDs merely correlate turns;
        # no access to the other creature's private memory is granted.
        message_id = f"{self.agent.id}:{self.agent.memory.next_id}"
        self.agent.experience.spoke(message_id, listener.agent.id)
        outgoing = {"id": message_id, "reply_to": reply_to, "direction": "sent", "state": "waiting",
                    "peer_id": listener.agent.id, "at": self.agent.lifetime_seconds}
        self.agent.dialogue.sent(reply_to)
        self.agent.memory.remember_story(self.world.tick, story, self.agent.id, self.agent.name, heard=False,
                                         listener_id=listener.agent.id, listener_name=listener.agent.name,
                                         utterance=outgoing)
        heard = listener.agent.memory.remember_story(self.world.tick, story, self.agent.id, self.agent.name,
                   utterance={**outgoing, "direction": "received", "state": "new", "peer_id": self.agent.id,
                              "at": listener.agent.lifetime_seconds})
        listener.agent.dialogue.received(heard)
        listener.agent.experience.heard_reply(reply_to, heard)
        listener.next_thought_lifetime = listener.agent.lifetime_seconds
        if listener.pending_kind == "plan":
            listener._dialogue_interrupt = True
        self.conversations += 1
        self.agent.last_result = f"Zwróciłam się do {listener.agent.name}; czekam na reakcję."
        self.agent.experience.outcome(self.agent.last_result + " Samo wypowiedzenie słów nie potwierdza oczekiwanej reakcji.")
        self.event(f"Do {listener.agent.name}", story, "talk", delivered=True, direction="sent",
                   speaker_id=self.agent.id, listener_id=listener.agent.id, listener_body=listener.body_state(),
                   message_id=message_id, in_reply_to=reply_to)
        listener.event(f"Od {self.agent.name}", story, "talk", delivered=True, direction="received",
                       speaker_id=self.agent.id, listener_id=listener.agent.id,
                       message_id=message_id, in_reply_to=reply_to)
        self.agent.plan.clear()
        self.phase = "observe"
        self.next_thought_lifetime = self.agent.lifetime_seconds

    def request_sleep(self, reason: str = "Sen wywołany przez obserwatora.") -> None:
        if self.agent.alive:
            self.sleep_requested, self.sleep_reason = True, reason

    def retry(self) -> None:
        if self.phase in ("error", "retrying") and self.agent.alive:
            self.error = ""
            self._submit(self.retry_kind or "plan")

    def update(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        # Charge everyone's elapsed life BEFORE delivering anyone's speech.
        for controller in list(self.controllers.values()):
            controller._elapse(now)
        for controller in list(self.controllers.values()):
            controller._update_behavior(now)

    def _elapse(self, now: float) -> None:
        if self.closed or self.phase == "dead":
            return
        elapsed = 0.0 if self._last_update_at is None else max(0.0, now - self._last_update_at)
        self._last_update_at = now
        self._motor_dt = 0.0 if self.paused else elapsed
        if self.paused:
            return
        # Life continues while waiting for API, sleeping, idling, or showing an error.
        self.agent.elapse(elapsed, self.phase)
        if not self.agent.alive:
            self._handle_death()
            return

    def _update_behavior(self, now: float) -> None:
        if self.closed or self.paused or not self.agent.alive:
            return
        if self.phase != "sleeping":
            self._refresh_senses()
        def connected(peer):
            target = self.world.entities.get(peer)
            # Lost contact outside sight does not disclose a cause.
            return target is not None and self.world.can_hear(self.agent, target)
        for note in self.agent.dialogue.expire(connected):
            self.event("Stan rozmowy", dialogue_label(note.utterance), "dialogue",
                       message_id=note.utterance["id"], state=note.utterance["state"])
        # The physical lane runs even during inference, narration and API retries.
        # A requested sleep stops the body immediately; its reflection waits for
        # the single in-flight cognitive request to finish.
        if self.sleep_requested:
            self._stop_body("Obserwator zażądał snu podczas działania.")
        if self.agent.motor is not None and self.phase != "sleeping":
            self._advance_motor(now)
        if not self.agent.alive:
            return
        if (self.agent.motor is None and self.agent.plan and not self.sleep_requested
                and self.phase != "sleeping" and now >= self.next_action_at):
            action = self.agent.plan[0]["action"]
            if action not in ("talk", "sleep"):
                self._start_body_command(now)
            elif self.pending is None and self.phase not in ("error", "retrying"):
                self.agent.plan.popleft()
                if action == "sleep":
                    self.request_sleep("Istota sama zaplanowała sen.")
                else:
                    if self._submit("talk") is False:
                        self.agent.plan.appendleft({"action": "talk"})
                        if self.agent.lifetime_seconds >= self.next_thought_lifetime:
                            self._submit("plan")
                return
        if not self.agent.alive:
            return
        # The cognitive lane has at most one request per creature. It never
        # writes the live body from its worker thread.
        if self.pending is not None:
            if self.pending.done():
                self._receive(now)
            return
        if self.phase == "error":
            return
        if self.sleep_requested and self.phase == "retrying" and self.retry_kind != "sleep":
            self.error = ""
            self.retry_count = 0
            self._submit("sleep")
            return
        if self.phase == "retrying":
            if now >= self.retry_at:
                self._submit(self.retry_kind or "plan")
            return
        finishing_plan = bool(self.agent.motor or self.agent.plan)
        if self.sleep_requested or (self.agent.needs_sleep and not finishing_plan):
            if not self.sleep_reason or not self.sleep_requested:
                self.sleep_reason = ("Pamięć zbliża się do limitu." if self.agent.memory.needs_sleep
                                     else "Ciało jest zmęczone.")
            self.event("Zasypianie", self.sleep_reason, "sleep")
            self._submit("sleep")
            return
        if self.agent.motor is not None:
            if self.agent.lifetime_seconds >= self.next_thought_lifetime:
                self._submit("plan")
            return
        if self.agent.plan or now < self.next_action_at:
            return
        if self.phase == "waking" or self.agent.lifetime_seconds >= self.next_thought_lifetime:
            self._submit("plan")

    def _start_body_command(self, now: float) -> None:
        command = self.agent.plan.popleft()
        self.agent.look(self.world, remember=True)
        self.agent.start_command(command)
        if self.pending is None and self.phase not in ("error", "retrying"):
            self.phase = "acting"
        self.event("Polecenie dla ciała", self.agent.intent, "motor_start", command=command)
        self._last_motor_log = now
        # No retroactive walking for the elapsed interval before this command.
        self._advance_motor(now, dt=0.0)

    def _advance_motor(self, now: float, dt: float | None = None) -> None:
        elapsed = self._motor_dt if dt is None else dt
        speed = .65 / self.action_delay if self.action_delay else 1.0
        remaining = elapsed * speed
        while self.agent.motor is not None:
            before = self.body_state()
            command = dict(self.agent.motor.command)
            target_id = command.get("target", "")
            other = self.controllers.get(target_id)
            displaced_before = other.body_state() if other else None
            step = min(remaining, .05)
            result = self.agent.step_motor(self.world, step)
            remaining -= step
            if result:
                self.event("Wynik polecenia" if result.success else "Niepowodzenie", result.message,
                           "eat" if result.action == "eat" and result.success else "action",
                           command=command, action=result.action, success=result.success,
                           before=before, energy_delta=result.energy_delta, displaced_id=result.displaced_id)
                if result.displaced_id and other:
                    other.agent.position = self.world.entities[result.displaced_id].position
                    if other.agent.alive:
                        if other.pending is not None and other.pending_kind == "plan":
                            other._replan_after_request = True
                        elif other.pending is None:
                            other.phase = "observe"
                    other.event("Popchnięcie", f"{self.agent.name} przesunęła ciało z "
                                f"{displaced_before['position']} na {list(other.agent.position)}.", "displacement",
                                before=displaced_before, instigator_id=self.agent.id)
                if not self.agent.alive:
                    self._handle_death()
                    return
                self.next_action_at = now + self.action_delay
                if self.pending is None and self.phase not in ("error", "retrying"):
                    self.phase = "acting" if self.agent.plan else "observe"
                    self.next_thought_lifetime = self.agent.lifetime_seconds
                break
            if remaining <= 1e-9:
                break
        if self.agent.motor and now - self._last_motor_log >= .5:
            self.event("Ruch ciała", self.agent.motor.status, "motor_progress",
                       command=self.agent.motor.command, distance=self.agent.motor.travelled)
            self._last_motor_log = now

    def save(self, path: Path) -> None:
        for controller in self.controllers.values():
            if not controller.agent.alive:
                controller.agent.position = self.world.entities[controller.agent.id].position
                controller._handle_death()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 5, "world": self.world.to_dict(),
            "agents": [c.agent.to_dict() for c in self.controllers.values()],
            "selected_agent": self.agent.id, "cycles": self.cycles,
            "observer_journal": self.journal.to_dict(),
            "controllers": {
                key: {"cycles": c.cycles, "conversations": c.conversations}
                for key, c in self.controllers.items()
            },
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        self.journal.flush()

    @classmethod
    def load(cls, path: Path, settings: Settings, brain: Brain | None = None) -> Simulation:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") not in (1, 2, 3, 4, 5):
            raise ValueError("Nieobsługiwana wersja zapisu.")
        world = World.from_dict(data["world"])
        for item in data["agents"]:
            item["memory"]["budget"] = max(item["memory"]["budget"], settings.memory_budget)
        agents = {item["id"]: Agent.from_dict(item) for item in data["agents"]}
        for agent in agents.values():
            world.add_agent(agent)
        journal = ObserverJournal.from_session(data)
        sim = cls(settings, brain, world=world, agent=agents[data["selected_agent"]],
                  journal=journal, record_birth=False)
        for agent in agents.values():
            if agent is not sim.agent:
                controller = cls(settings, world=world, agent=agent, journal=journal, record_birth=False)
                controller.controllers = sim.controllers
                sim.controllers[agent.id] = controller
        for key, controller in sim.controllers.items():
            saved = data.get("controllers", {}).get(key, data if key == sim.agent.id else {})
            controller.cycles = saved.get("cycles", 0)
            controller.conversations = saved.get("conversations", 0)
            if controller.agent.alive:
                controller.agent.visible = world.perceive(controller.agent)
                controller.event("Wczytano", "Odtworzono ciało i pamięć. Istota przygotuje nowy plan.", "system")
            else:
                controller._handle_death()
        return sim

    def close(self) -> None:
        for controller in self.controllers.values():
            controller.closed = True
            controller._terminated.set()
            if controller.pending:
                controller.pending.cancel()
        self.journal.flush()


def run_headless(sim: Simulation, steps: int, sleep_at: int | None = None) -> dict:
    for controller in sim.controllers.values():
        controller.action_delay = 0
    total_age = lambda: sum(c.agent.age for c in sim.controllers.values())
    initial_age = total_age()
    requested = False
    deadline = time.monotonic() + max(120, steps * (sim.settings.timeout + 1))
    simulated_now = time.monotonic()
    previous_wall = simulated_now
    while total_age() - initial_age < steps:
        if sleep_at is not None and not requested and total_age() - initial_age >= sleep_at:
            sim.request_sleep("Kontrolowana retrospekcja w teście integracyjnym.")
            requested = True
        wall = time.monotonic()
        increment = max(0, wall - previous_wall)
        if any(c.agent.motor for c in sim.controllers.values()):
            increment = max(.05, increment)
        simulated_now += increment
        previous_wall = wall
        sim.update(simulated_now)
        if not any(c.agent.alive for c in sim.controllers.values()):
            break
        if time.monotonic() > deadline:
            raise BrainError("Przekroczono czas testu symulacji.")
        time.sleep(0.005)
    return {
        "model": sim.brain.model, "steps": total_age() - initial_age,
        "cycles": sim.cycles, "position": list(sim.agent.position),
        "energy": round(sim.agent.energy, 2), "meals": sim.agent.meals,
        "alive": sim.agent.alive, "lifetime_seconds": round(sim.agent.lifetime_seconds, 2),
        "memory": sim.agent.memory.capacity(), "last_sleep": sim.agent.memory.last_sleep,
        "agents": [
            {"id": c.agent.id, "alive": c.agent.alive, "energy": round(c.agent.energy, 2),
             "actions": c.agent.age, "stories_told": c.conversations,
             "testimonies_remembered": sum(e.source == "testimony" for e in c.agent.memory.nodes)}
            for c in sim.controllers.values()
        ],
    }
