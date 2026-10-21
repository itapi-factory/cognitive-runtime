"""Continuous geometry. World contents never cross the sensory boundary wholesale."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING
from .conversation import TALK_RANGE
if TYPE_CHECKING:
    from .agent import Agent

Position = tuple[float, float]
BODY_RADIUS = 0.32


class Direction(IntEnum):
    """Cardinal constructors and legacy-save conversion; not the movement model."""
    NORTH = 0
    EAST = 1
    SOUTH = 2
    WEST = 3


class Heading(float):
    """Degrees clockwise from east in screen/world coordinates."""
    def __new__(cls, degrees=0):
        if isinstance(degrees, Direction):
            degrees = (int(degrees) * 90 - 90) % 360
        if not math.isfinite(degrees):
            raise ValueError("Kierunek musi być skończoną liczbą.")
        return float.__new__(cls, degrees % 360)

    @property
    def vector(self):
        a = math.radians(self)
        return math.cos(a), math.sin(a)

    @property
    def label(self):
        return f"{float(self):.1f}° (0° wschód, 90° południe)"

    @property
    def name(self):
        return f"{float(self):.2f}deg"

    def ahead(self, position, distance=1):
        dx, dy = self.vector
        return position[0] + dx * distance, position[1] + dy * distance


def angle_to(a: Position, b: Position) -> Heading:
    return Heading(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))


def angle_delta(a: float, b: float) -> float:
    return (b - a + 180) % 360 - 180


def segment_distance(point: Position, a: Position, b: Position) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = max(0., min(1., ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2)) if length2 else 0
    return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)


class Tile(StrEnum):
    EMPTY = "empty"
    WALL = "wall"
    ROCK = "rock"
    FOOD = "food"


def relative_description(forward: float, right: float) -> str:
    if math.hypot(forward, right) < 0.05:
        return "pod moim ciałem"
    parts = []
    if abs(forward) >= .05:
        parts.append(f"{abs(forward):.1f} m {'przede mną' if forward > 0 else 'za mną'}")
    if abs(right) >= .05:
        parts.append(f"{abs(right):.1f} m po mojej {'prawej' if right > 0 else 'lewej'} stronie")
    return ", ".join(parts)


@dataclass(frozen=True)
class SeenObject:
    x: float
    y: float
    kind: str
    name: str = ""
    appearance: str = ""
    id: str = ""
    radius: float = .2
    alive: bool | None = None

    @property
    def position(self):
        return self.x, self.y

    def to_dict(self):
        result = {"x": round(self.x, 3), "y": round(self.y, 3), "kind": self.kind,
                  "id": self.id, "radius": self.radius}
        if self.name:
            result["name"] = self.name
        if self.appearance:
            result["appearance"] = self.appearance
        if self.alive is not None:
            result["alive"] = self.alive
        return result


@dataclass
class WorldObject:
    id: str
    kind: str
    position: Position
    radius: float

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "position": list(self.position), "radius": self.radius}


@dataclass(frozen=True)
class Corpse:
    id: str
    name: str
    position: Position
    facing: Heading
    radius: float = BODY_RADIUS

    @property
    def alive(self):
        return False


class World:
    def __init__(self, width: float = 25, height: float = 21, seed: int = 42, *, generate=True):
        self.width, self.height, self.seed = float(width), float(height), seed
        self.rng = random.Random(seed)
        self.tick = 0
        self.entities: dict[str, Agent | Corpse] = {}
        self.objects: dict[str, WorldObject] = {}
        self.next_object = 1
        if generate:
            self._generate()

    def _generate(self):
        center = (self.width / 2, self.height / 2)
        for kind, count, radius in (("rock", 32, .48), ("food", 32, .18)):
            for _ in range(count):
                for _attempt in range(200):
                    p = (self.rng.uniform(1, self.width - 1), self.rng.uniform(1, self.height - 1))
                    if kind == "rock" and math.dist(p, center) < 3:
                        continue
                    if self.clear_position(p, radius + .35) and not self.object_at(p, .45):
                        self.add_object(kind, p, radius)
                        break
        self.add_object("food", (center[0] + 2, center[1]), .18)

    def add_object(self, kind, position, radius=None, *, identity=None):
        if kind not in ("food", "rock", "wall"):
            raise ValueError("Nieznany element świata.")
        radius = radius if radius is not None else (.18 if kind == "food" else .48)
        position = tuple(map(float, position))
        if not self.inside(position, radius) or not math.isfinite(radius) or radius <= 0:
            raise ValueError("Obiekt poza areną lub nieprawidłowy promień.")
        identity = identity or f"{kind}-{self.next_object}"
        if identity in self.objects or identity in self.entities:
            raise ValueError("Powtórzone ID obiektu.")
        self.next_object += 1
        obj = WorldObject(identity, kind, position, radius)
        self.objects[obj.id] = obj
        return obj

    def inside(self, p, radius=0):
        return (all(math.isfinite(v) for v in p) and radius <= p[0] <= self.width - radius
                and radius <= p[1] <= self.height - radius)

    def solids(self, excluding=()):
        return [o for o in [*self.objects.values(), *self.entities.values()]
                if o.id not in excluding and getattr(o, "kind", "body") != "food"]

    def clear_position(self, pos, radius=BODY_RADIUS, excluding=()):
        return self.inside(pos, radius) and all(
            math.dist(pos, o.position) >= radius + o.radius - 1e-8 for o in self.solids(excluding))

    def clear_segment(self, a, b, radius=BODY_RADIUS, excluding=()):
        return self.inside(b, radius) and all(
            segment_distance(o.position, a, b) >= radius + o.radius - 1e-8
            for o in self.solids(excluding))

    def occupant(self, pos, excluding=""):
        return next((a for a in self.entities.values()
                     if a.id != excluding and math.dist(pos, a.position) <= a.radius), None)

    def object_at(self, pos, reach=0):
        return next((o for o in self.objects.values() if math.dist(pos, o.position) <= o.radius + reach), None)

    def tile(self, pos):
        """Point query retained for importers; there is no backing grid."""
        if not self.inside(pos):
            return Tile.WALL
        obj = self.object_at(pos)
        return Tile(obj.kind) if obj else Tile.EMPTY

    def walkable(self, pos, excluding=""):
        return self.clear_position(pos, excluding=(excluding,))

    def add_agent(self, agent):
        if agent.id in self.entities or not self.clear_position(agent.position):
            raise ValueError("Zajęta pozycja lub powtórzone ID istoty.")
        self.entities[agent.id] = agent
        if not agent.alive:
            self.leave_corpse(agent)

    def leave_corpse(self, agent):
        if agent.alive:
            raise ValueError("Żywa istota nie jest zwłokami.")
        self.entities[agent.id] = Corpse(agent.id, agent.name, agent.position, agent.facing)

    def line_of_sight(self, start, end, excluding=()):
        return all(segment_distance(o.position, start, end) >= o.radius - 1e-6
                   for o in self.solids(excluding))

    def point_visible(self, agent, pos, *, excluding=()):
        distance = math.dist(agent.position, pos)
        return (distance <= agent.vision_range and
                (distance < .05 or abs(angle_delta(agent.facing, angle_to(agent.position, pos))) <= 45.001) and
                self.line_of_sight(agent.position, pos, (agent.id, *excluding)))

    def perceive(self, agent):
        visible = []
        for obj in [*self.objects.values(), *self.entities.values()]:
            if obj.id == agent.id:
                continue
            if self.point_visible(agent, obj.position, excluding=(obj.id,)):
                body = obj.id in self.entities
                visible.append(SeenObject(*obj.position, f"agent:{obj.id}" if body else obj.kind,
                    obj.name if body else "",
                    "martwa istota; nie rusza się, nie działa i nie może odpowiedzieć" if body and not obj.alive else "",
                    obj.id, obj.radius, obj.alive if body else None))
        return sorted(visible, key=lambda o: (math.dist(agent.position, o.position), o.id))

    def can_address(self, speaker, listener):
        return (speaker.alive and listener.alive and speaker.id != listener.id and
                math.dist(speaker.position, listener.position) <= TALK_RANGE and
                self.point_visible(speaker, listener.position, excluding=(listener.id,)))

    def can_talk(self, speaker, listener):
        return listener.alive and self.can_address(speaker, listener)

    def can_hear(self, speaker, listener):
        return (speaker.alive and listener.alive and speaker.id != listener.id and
                math.dist(speaker.position, listener.position) <= TALK_RANGE and
                self.line_of_sight(speaker.position, listener.position, (speaker.id, listener.id)))

    def push(self, actor, target_id, distance):
        target = self.objects.get(target_id) or self.entities.get(target_id)
        if target is None or getattr(target, "kind", "body") not in ("rock", "body"):
            return False, "Nie wyczuwam obiektu, który można pchnąć.", ""
        if math.dist(actor.position, target.position) > actor.radius + target.radius + .18:
            return False, "Nie sięgam wybranego obiektu.", ""
        direction = angle_to(actor.position, target.position)
        destination = direction.ahead(target.position, distance)
        actor_destination = direction.ahead(actor.position, distance)
        excluded = (actor.id, target.id)
        food_blocked = any(segment_distance(o.position, target.position, destination) < target.radius + o.radius
                           for o in self.objects.values() if o.kind == "food")
        if (food_blocked or not self.clear_segment(target.position, destination, target.radius, excluded)
                or not self.clear_segment(actor.position, actor_destination, actor.radius, excluded)):
            return False, "Opór: za wybranym obiektem brakuje miejsca na pchnięcie.", ""
        before = target.position
        actor.position = actor_destination
        if isinstance(target, Corpse):
            self.entities[target.id] = replace(target, position=destination)
        else:
            target.position = destination
            if hasattr(target, "motor"):
                target.cancel_activity()
                target.last_result = f"Moje ciało zostało popchnięte z {before} do {destination}. To nie był mój krok."
                target.memory.remember(self.tick, target.last_result, .9)
        return True, f"Przepchnęłam obiekt {target.id} o {distance:.2f} m.", target.id if target.id in self.entities else ""

    def advance(self):
        self.tick += 1

    def to_dict(self):
        return {"geometry": "continuous", "width": self.width, "height": self.height, "seed": self.seed,
                "tick": self.tick, "objects": [o.to_dict() for o in self.objects.values()],
                "next_object": self.next_object, "rng": self.rng.getstate()}

    @classmethod
    def from_dict(cls, data):
        world = cls(data["width"], data["height"], data["seed"], generate=False)
        world.tick = data["tick"]
        if "grid" in data:
            # Import historical positions once; old archives remain unchanged.
            for y, row in enumerate(data["grid"]):
                for x, kind in enumerate(row):
                    if kind in ("rock", "food") or (kind == "wall" and 0 < x < world.width - 1 and 0 < y < world.height - 1):
                        world.add_object(kind, (x, y))
        else:
            for item in data["objects"]:
                world.add_object(item["kind"], item["position"], item["radius"], identity=item["id"])
            world.next_object = data["next_object"]
        if "rng" in data:
            state = data["rng"]
            world.rng.setstate((state[0], tuple(state[1]), state[2]))
        return world
