from __future__ import annotations

from collections import deque

import math

from .brain import Plan
from .conversation import Dialogue, TALK_RANGE
from .energy import ENERGY
from .memory import Memory
from .world import BODY_RADIUS, Direction, Heading, Position, SeenObject, World
from .motor import Motor, ActionResult
from .experience import Experience


class Agent:
    """Reusable body + bounded autobiographical memory, independent of rendering."""

    def __init__(
        self, agent_id: str, position: Position, facing: Direction = Direction.EAST,
        *, memory_budget: int = 8000, vision_range: int = 6, name: str = "Ada",
    ):
        self.id, self.name = agent_id, name
        self.position, self.facing = tuple(map(float, position)), facing
        self.radius = BODY_RADIUS
        self.motor: Motor | None = None
        self.activity_revision = 0
        self.vision_range = vision_range
        self.memory = Memory(memory_budget)
        self.dialogue = Dialogue(self)
        self.experience = Experience(self)
        self.energy = 78.0
        self.dead = False
        self.death_reason = ""
        self.lifetime_seconds = 0.0
        self.fatigue = 0.0
        self.age = 0
        self.meals = 0
        self.goal = "Poznać otoczenie i zbadać własne możliwości."
        self.intent = "Rozglądam się po raz pierwszy."
        self.plan: deque[dict] = deque()
        self.talk_target = ""
        self.speech_intent = ""
        self.last_sleep_age = -12
        self.conversation_partners: list[dict] = []
        self.visible: list[SeenObject] = []
        self.death_notice_revision = 0
        self.death_notice = ""
        self.last_result = "Dopiero pojawiłam się na arenie."
        self.memory.remember(0, f"Budząc się, mam pozycję {position}. Nic nie wiem o świecie.", 0.6)

    @property
    def facing(self) -> Heading:
        return self._facing

    @facing.setter
    def facing(self, value):
        self._facing = Heading(value)

    @property
    def alive(self) -> bool:
        return not self.dead and self.energy > 0

    def die(self, reason: str = "Brak energii.") -> None:
        self.dead = True
        self.energy = 0.0
        self.death_reason = reason
        self.memory.erase()
        self.cancel_activity()
        self.plan.clear()
        self.talk_target = ""
        self.speech_intent = ""
        self.conversation_partners.clear()
        self.visible.clear()
        self.death_notice = ""
        self.goal = self.intent = self.last_result = ""

    def spend_energy(self, amount: float, reason: str) -> bool:
        """Pay before an operation: crossing zero prevents even eating or waking."""
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Koszt energii musi być skończony i nieujemny.")
        if not self.alive:
            self.die(self.death_reason or reason)
            return False
        self.energy = max(0.0, self.energy - amount)
        if self.energy <= 0:
            self.die(reason)
            return False
        return True

    def elapse(self, seconds: float, phase: str) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("Upływ czasu musi być skończony i nieujemny.")
        if not self.alive:
            self.die(self.death_reason or "Brak energii.")
            return
        rate = ENERGY.per_second(phase)
        self.lifetime_seconds += min(seconds, self.energy / rate)
        self.spend_energy(seconds * rate, "Energia wyczerpała się podczas życia lub pracy umysłu.")

    @property
    def mouth_position(self) -> Position:
        return self.facing.ahead(self.position, self.radius + .14)

    @property
    def mobility(self) -> float:
        return .35 + .65 * min(1., max(0., self.energy) / 20.)

    @property
    def movement_speed(self) -> float:
        return Motor.speed * self.mobility

    @property
    def needs_sleep(self) -> bool:
        return self.alive and (self.fatigue >= 94 or
                               (self.memory.needs_sleep and self.age - self.last_sleep_age >= 12))

    def look(self, world: World, *, remember=False) -> None:
        if not self.alive:
            return
        already_visible_dead = {item.id for item in self.visible if item.alive is False}
        self.visible = world.perceive(self)
        for item in self.visible:
            if item.alive is False:
                previous = self.memory.target(item.id)
                changed = self.dialogue.recognize_dead(item.id)
                if ((not previous or previous.get("alive") is not False) and
                        item.id not in already_visible_dead) or changed:
                    self.memory.observe(item.to_dict(), world.tick)
                    self.death_notice_revision += 1
                    self.death_notice = f"Widzę: martwa istota {item.name}. Nie może już odpowiedzieć. Przyczyny śmierci nie znam."
                self.experience.recognize_dead(item.id, item.name)
        self.conversation_partners = [
            {"id": a.id, "name": a.name, "position": list(a.position)}
            for a in world.entities.values() if world.can_address(self, a) or
            (self.dialogue.recent_contact(a.id) and world.can_hear(self, a))
        ]
        if remember:
            for item in self.visible:
                if item.kind == "food" or item.kind.startswith("agent:"):
                    self.memory.observe(item.to_dict(), world.tick)

    def known_target(self, identity: str) -> dict | None:
        visible = next((o for o in self.visible if o.id == identity), None)
        if visible:
            return visible.to_dict()
        return self.memory.target(identity)

    def start_command(self, command: dict) -> None:
        if not self.alive:
            raise ValueError("Martwa istota nie może działać.")
        motor = Motor(command, self)
        self.activity_revision += 1
        self.motor = motor
        self.experience.start()

    def cancel_activity(self, reason="Przerwano wykonanie mojego zamiaru.") -> None:
        """Invalidate decisions based on an activity that no longer exists."""
        if self.motor is not None or self.plan:
            self.activity_revision += 1
        self.motor = None
        self.plan.clear()
        self.experience.interrupt(reason)

    def activity_snapshot(self) -> dict:
        motor = self.motor
        activity = {"active": motor is not None, "revision": self.activity_revision,
                    "queued_commands": [dict(c) for c in self.plan]}
        if motor:
            activity.update({"command": dict(motor.command), "status": motor.status,
                             "elapsed_seconds": round(motor.elapsed, 2),
                             "travelled_metres": round(motor.travelled, 2),
                             "destination": list(motor.goal) if motor.action not in ("look", "wait") else None,
                             "target": dict(motor.target) if motor.target else None})
        else:
            activity["status"] = "Ciało nie wykonuje teraz polecenia ruchowego."
        return activity

    def step_motor(self, world: World, dt: float) -> ActionResult | None:
        if not self.alive or self.motor is None:
            return None
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Nieprawidłowy krok czasu ruchu.")
        motor = self.motor
        motor.time_bank += dt
        result = None
        if not motor.started:
            result = motor.step(self, world, 0.)
        while result is None and self.alive and motor.time_bank >= .02 - 1e-10:
            motor.time_bank = max(0., motor.time_bank - .02)
            result = motor.step(self, world, .02)
        if result:
            self.activity_revision += 1
            self.motor = None
            if self.alive:
                self.look(world, remember=True)
            else:
                world.leave_corpse(self)
        return result

    def snapshot(self, max_plan: int = 5) -> dict:
        if not self.alive:
            raise ValueError("Martwa istota nie ma kontekstu do analizy.")
        # Only the bounded memory and current senses cross the LLM boundary.
        fx, fy = self.facing.vector
        return {
            "self": {
                "id": self.id, "name": self.name, "position": list(self.position),
                "facing": self.facing.name.lower(), "energy": round(self.energy, 1),
                "facing_label": self.facing.label,
                "energy_capacity": ENERGY.capacity,
                "lifetime_seconds": round(self.lifetime_seconds, 2),
                "meals": self.meals,
                "fatigue": round(self.fatigue, 1), "age_actions": self.age,
                "vision_range_m": self.vision_range,
                "mouth_position": list(self.mouth_position),
                "heading_degrees": float(self.facing),
                "motor_status": self.motor.status if self.motor else "Brak wykonywanego polecenia.",
                "movement_speed": round(self.movement_speed, 3),
                "goal": self.goal, "last_action_result": self.last_result,
            },
            "body_activity": self.activity_snapshot(),
            "memory_capacity": self.memory.capacity(),
            "memory": self.memory.context(),
            "memory_ids": sorted(self.memory.valid_ids),
            "perception": [
                {**c.to_dict(),
                 "forward": (c.x - self.position[0]) * fx + (c.y - self.position[1]) * fy,
                 "right": -(c.x - self.position[0]) * fy + (c.y - self.position[1]) * fx}
                for c in self.visible
            ],
            "conversation": {
                "range_m": TALK_RANGE, "partners": list(self.conversation_partners),
                "only_narrative": True, "dump_forbidden": True,
                "heard_stories_are_unverified": True,
                **self.dialogue.snapshot(),
            },
            "known_targets": [n.observation for n in self.memory.nodes if n.observation],
            "experience": self.experience.snapshot(),
            "recalled_ids": self.memory.related(
                self.goal + " " + self.intent + " " + self.last_result + " " +
                " ".join(o.name + " " + o.appearance for o in self.visible),
                identities=[o.id for o in self.visible]),
            "max_plan": max_plan,
        }

    def accept_plan(self, plan: Plan, tick: int | None = None, *, remember_thought: bool = True) -> None:
        if not self.alive:
            return
        self.goal, self.intent = plan.goal, plan.intent
        self.plan = deque(plan.actions)
        self.talk_target = plan.listener_id
        self.speech_intent = plan.speech_intent
        self.experience.begin(plan, self.age if tick is None else tick)
        if remember_thought:
            self.memory.add_thought(plan.thought, self.age if tick is None else tick)

    def sense_body(self, tick: int, activity: str) -> None:
        """Remember measured body state, without supplying its causal explanation."""
        if self.alive:
            sample = self.experience.reading()
            previous = next((i.body for i in reversed(self.memory.impressions) if i.body), None)
            change = (f" Od poprzedniego odczytu ({sample['time'] - previous['time']:.1f} s): "
                      f"energia {sample['energy'] - previous['energy']:+.2f}, "
                      f"dostępna szybkość chodu {previous['speed']:.2f} → {sample['speed']:.2f} m/s."
                      if previous else f" Dostępna szybkość chodu: {sample['speed']:.2f} m/s.")
            self.memory.remember(
                tick, f"{activity} Czas życia {self.lifetime_seconds:.1f} s; "
                f"energia {self.energy:.2f}/{ENERGY.capacity:g}; zmęczenie {self.fatigue:.1f}." + change,
                0.5, body=sample,
            )

    def wake(self, reflection: str, world: World, *, context_ids: set[int] | None = None) -> dict | None:
        before = self.energy
        cost = ENERGY.consolidation_cost(self.memory.used)
        if not self.spend_energy(cost, "Brak energii na porządkowanie pamięci."):
            world.leave_corpse(self)
            return None
        report = self.memory.consolidate(reflection, context_ids=context_ids)
        report["energy_cost"] = round(cost, 3)
        self.fatigue = max(0, self.fatigue - 72)
        self.age += 1
        self.last_sleep_age = self.age
        world.advance()
        self.plan.clear()
        self.last_result = (f"Sen zakończony. Uporządkowałam pamięć. "
                            f"Energia przed porządkowaniem: {before:.2f}, po: {self.energy:.2f}.")
        self.experience.outcome(self.last_result)
        # Don't immediately refill the memory that was just consolidated.
        self.visible = world.perceive(self)
        return report

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "position": list(self.position),
            "heading": float(self.facing), "vision_range": self.vision_range,
            "activity_revision": self.activity_revision,
            "energy": self.energy, "fatigue": self.fatigue, "age": self.age,
            "dead": self.dead, "death_reason": self.death_reason,
            "lifetime_seconds": self.lifetime_seconds,
            "last_sleep_age": self.last_sleep_age,
            "meals": self.meals, "goal": self.goal, "intent": self.intent,
            "last_result": self.last_result, "memory": self.memory.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Agent:
        agent = cls(data["id"], tuple(data["position"]),
                    Heading(data["heading"]) if "heading" in data else Direction(data["facing"]),
                    memory_budget=data["memory"]["budget"],
                    vision_range=data["vision_range"], name=data["name"])
        for key in ("energy", "fatigue", "age", "meals", "goal", "intent", "last_result"):
            setattr(agent, key, data[key])
        agent.memory = Memory.from_dict(data["memory"])
        agent.activity_revision = data.get("activity_revision", 0)
        agent.lifetime_seconds = data.get("lifetime_seconds", 0.0)
        agent.last_sleep_age = data.get("last_sleep_age", -12)
        if data.get("dead") or agent.energy <= 0 or agent.memory.erased:
            agent.die(data.get("death_reason") or "Brak energii w zapisanym stanie.")
        else:
            agent.experience.interrupt("Wczytano sesję; wcześniejsza aktywność nie została wznowiona. Wyniku nie znam.")
        return agent
