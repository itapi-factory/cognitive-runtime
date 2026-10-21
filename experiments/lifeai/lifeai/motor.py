"""Deterministic, bounded execution of goals. No hunger policy and no LLM calls."""
from __future__ import annotations
import heapq
import math
from dataclasses import dataclass
from .world import BODY_RADIUS, Heading, angle_delta, angle_to, segment_distance
from .energy import ENERGY

COMMANDS = ("go_to", "eat", "push", "look", "explore", "wait", "sleep", "talk")


def number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name}: oczekuję skończonej liczby od {low} do {high}.")
    return float(value)


def validate_command(command):
    if not isinstance(command, dict) or command.get("action") not in COMMANDS:
        raise ValueError("Polecenie musi być obiektem z dozwolonym polem action.")
    action = command["action"]
    c = {"action": action}
    allowed = {"action"}
    if action in ("eat", "push") or (action == "go_to" and "target" in command):
        target = command.get("target")
        if not isinstance(target, str) or not target or len(target) > 80:
            raise ValueError("Wybierz target: identyfikator widzianego lub zapamiętanego obiektu.")
        c["target"] = target
        allowed.add("target")
    elif action == "go_to":
        p = command.get("position")
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise ValueError("go_to wymaga target albo position: [x,y].")
        c["position"] = [number(v, -1000, 1000, "position") for v in p]
        allowed.add("position")
    if action in ("look", "explore"):
        c["angle"] = number(command.get("angle"), 0, 360, "angle") % 360
        allowed.add("angle")
    if action in ("explore", "push"):
        c["distance"] = number(command.get("distance", 3 if action == "explore" else .6),
                               .1, 8 if action == "explore" else 1, "distance")
        allowed.add("distance")
    if action == "wait":
        c["seconds"] = number(command.get("seconds", 1), .1, 10, "seconds")
        allowed.add("seconds")
    if set(command) - allowed:
        raise ValueError(f"Nieznane pola polecenia {action}: {', '.join(sorted(set(command) - allowed))}.")
    return c


def route(start, goal, obstacles, bounds, radius=BODY_RADIUS):
    """Visibility graph around observed circles, never a grid or a world lookup."""
    margin = .035
    # Contact may leave the body inside a preferred clearance margin. Preserve
    # its physical radius but allow an outward route from that valid position.
    circles = [(p, max(r + radius, min(r + radius + margin, math.dist(start, p) - 1e-5)))
               for p, r in obstacles]

    def inside(p):
        return radius <= p[0] <= bounds[0] - radius and radius <= p[1] <= bounds[1] - radius

    def clear(a, b):
        return inside(b) and all(segment_distance(p, a, b) >= r - 1e-7 for p, r in circles)

    if not inside(goal) or any(math.dist(goal, p) < r for p, r in circles):
        return []
    if clear(start, goal):
        return [goal]
    nodes = [start, goal]
    for p, r in circles:
        # Circumscribed polygon: adjacent chords also clear the circle.
        rr = (r + .02) / math.cos(math.pi / 8)
        for i in range(8):
            point = Heading(i * 45).ahead(p, rr)
            if inside(point) and all(math.dist(point, q) >= qr for q, qr in circles):
                nodes.append(point)
    edges = [[] for _ in nodes]
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            if clear(a, nodes[j]):
                length = math.dist(a, nodes[j])
                edges[i].append((j, length))
                edges[j].append((i, length))
    pending, distances, parent = [(0, 0)], {0: 0}, {}
    while pending:
        cost, i = heapq.heappop(pending)
        if cost != distances[i]:
            continue
        if i == 1:
            path = []
            while i:
                path.append(nodes[i])
                i = parent[i]
            return list(reversed(path))
        for j, length in edges[i]:
            distance = cost + length
            if distance < distances.get(j, math.inf):
                distances[j], parent[j] = distance, i
                heapq.heappush(pending, (distance, j))
    return []


@dataclass(frozen=True)
class ActionResult:
    action: str
    success: bool
    message: str
    energy_delta: float
    displaced_id: str = ""


class Motor:
    speed = 1.4                  # metres / simulated second
    turn_speed = 180.0           # degrees / simulated second

    def __init__(self, command, agent):
        self.command = validate_command(command)
        self.action = command["action"]
        self.origin = agent.position
        self.energy_before = agent.energy
        self.elapsed = self.travelled = self.turned = self.time_bank = 0.
        self.path = []
        self.obstacles = {}      # working set exists only during this one command
        self.target = agent.known_target(command.get("target", ""))
        self.goal = tuple(command.get("position", agent.position))
        self.status = "Rozpoczynam polecenie."
        self.error = ""
        self.started = False
        self.scanned = False
        self.scan_remaining = 0.
        self.replans = 0
        if "target" in command:
            if self.target is None:
                self.error = "Nie pamiętam wskazanego obiektu. Potrzebuję go najpierw dostrzec."
            elif self.action == "eat" and self.target["kind"] != "food":
                self.error = "Wybrany obiekt nie jest jedzeniem."
        if self.action == "explore":
            self.goal = Heading(command["angle"]).ahead(agent.position, command["distance"])

    def _finish(self, agent, world, success, message, displaced=""):
        world.advance()
        agent.age += 1
        agent.fatigue = min(100, agent.fatigue + .8)
        delta = agent.energy - self.energy_before
        result = ActionResult(self.action, success, message, delta, displaced)
        if agent.alive:
            agent.last_result = (f"{message} Przebyłam {self.travelled:.2f} m. "
                                 f"Energia: {self.energy_before:.2f} → {agent.energy:.2f} ({delta:+.2f}).")
            agent.memory.remember(world.tick, agent.last_result, .9)
            agent.experience.outcome(agent.last_result, failed=not success)
            if not success:
                agent.plan.clear()
        return result

    def _turn(self, agent, desired, dt):
        difference = angle_delta(agent.facing, desired)
        amount = min(abs(difference), self.turn_speed * agent.mobility * dt)
        if amount and not agent.spend_energy(amount * ENERGY.turn_per_degree, "Brak energii na obrót."):
            return False
        agent.facing = Heading(agent.facing + math.copysign(amount, difference))
        self.turned += amount
        agent.fatigue = min(100, agent.fatigue + amount * .003)
        return abs(difference) <= amount + 1e-6

    def step(self, agent, world, dt):
        if not self.started:
            self.started = True
            if not agent.spend_energy(ENERGY.action, "Brak energii na rozpoczęcie działania."):
                return self._finish(agent, world, False, "Ciało przestało działać.")
        if self.error:
            return self._finish(agent, world, False, self.error)
        self.elapsed += dt
        if self.elapsed > 45:
            return self._finish(agent, world, False, "Przerwałam próbę: zbyt długo nie osiągam celu.")
        agent.look(world)
        seen = {o.id: o for o in agent.visible}
        for o in agent.visible:
            if o.kind == "rock" or o.kind == "wall" or o.kind.startswith("agent:"):
                self.obstacles[o.id] = (o.position, o.radius)
        # Forget stale observed obstacles when their old location can be inspected.
        for identity, (pos, _) in list(self.obstacles.items()):
            if identity not in seen and world.point_visible(agent, pos, excluding=(identity,)):
                del self.obstacles[identity]
        self.obstacles = dict(sorted(self.obstacles.items(), key=lambda item: math.dist(agent.position, item[1][0]))[:24])
        if self.target:
            observed = seen.get(self.target["id"])
            if observed:
                old = (self.target["x"], self.target["y"])
                self.target = observed.to_dict()
                if math.dist(old, observed.position) > .15:
                    self.path.clear()
            elif world.point_visible(agent, (self.target["x"], self.target["y"]), excluding=(self.target["id"],)):
                agent.memory.forget_target(self.target["id"])
                return self._finish(agent, world, False, "Dotarłam wzrokiem do zapamiętanego miejsca, ale wybranego obiektu już tam nie widzę.")
        if self.action == "wait":
            self.status = "Obserwuję otoczenie."
            if self.elapsed >= self.command["seconds"]:
                return self._finish(agent, world, True, "Zatrzymałam się i rozejrzałam.")
            return None
        if self.action == "look":
            self.status = "Obracam ciało i oczy."
            done = self._turn(agent, self.command["angle"], dt)
            if done or not agent.alive:
                agent.look(world)
                return self._finish(agent, world, done, f"Zwróciłam oczy w kierunku {float(agent.facing):.1f}°.")
            return None
        if self.scan_remaining > 0:
            amount = min(self.scan_remaining, self.turn_speed * agent.mobility * dt)
            self._turn(agent, agent.facing + amount, dt)
            self.scan_remaining -= amount
            self.status = "Rozglądam się za przejściem."
            if not agent.alive:
                return self._finish(agent, world, False, "Ciało przestało działać.")
            return None
        if self.target:
            center = (self.target["x"], self.target["y"])
            stand_off = agent.radius + self.target["radius"] + .08
            direction = angle_to(center, agent.position)
            goal = direction.ahead(center, stand_off)
            if math.dist(agent.position, center) <= stand_off + .025 and math.dist(agent.position, center) >= stand_off - .08:
                self.path.clear()
                self.status = "Ustawiam ciało przy celu."
                if not self._turn(agent, angle_to(agent.position, center), dt):
                    if not agent.alive:
                        return self._finish(agent, world, False, "Ciało przestało działać.")
                    return None
                # Interaction requires a fresh observation, not a hidden world read.
                agent.look(world)
                if not any(o.id == self.target["id"] for o in agent.visible):
                    return self._finish(agent, world, False, "Nie mogę dosięgnąć wskazanego celu.")
                if self.action == "eat":
                    food = world.objects.get(self.target["id"])
                    if food is None or food.kind != "food":
                        return self._finish(agent, world, False, "Jedzenie nie jest już dostępne.")
                    if not agent.spend_energy(ENERGY.action, "Brak energii na jedzenie."):
                        return self._finish(agent, world, False, "Ciało przestało działać przed jedzeniem.")
                    del world.objects[food.id]
                    agent.energy = min(ENERGY.capacity, agent.energy + ENERGY.food)
                    agent.meals += 1
                    agent.memory.forget_target(food.id)
                    return self._finish(agent, world, True, f"Podeszłam do jedzenia {food.id} przy {food.position} i zjadłam je.")
                if self.action == "push":
                    if not agent.spend_energy(ENERGY.push_per_metre * self.command["distance"], "Brak energii na pchnięcie."):
                        return self._finish(agent, world, False, "Ciało przestało działać przed pchnięciem.")
                    success, message, displaced = world.push(agent, self.target["id"], self.command["distance"])
                    return self._finish(agent, world, success, message, displaced)
                return self._finish(agent, world, True, f"Podeszłam do obiektu {self.target['id']} przy {center}.")
            # Keep a chosen approach point stable while walking around obstacles.
            if not self.path:
                self.goal = goal
        if math.dist(agent.position, self.goal) < .025:
            return self._finish(agent, world, True, f"Dotarłam do miejsca ({agent.position[0]:.2f}, {agent.position[1]:.2f}).")
        known = list(self.obstacles.values())
        if not self.path:
            self.replans += 1
            self.path = route(agent.position, self.goal, known, (world.width, world.height))
            if not self.path:
                if not self.scanned:
                    self.scanned, self.scan_remaining = True, 360.
                    return None
                return self._finish(agent, world, False, "Nie znalazłam przejścia do wybranego celu; przeszkoda blokuje dojście.")
        point = self.path[0]
        self.status = f"Idę do ({self.goal[0]:.2f}, {self.goal[1]:.2f}); omijam dostrzeżone przeszkody."
        desired = angle_to(agent.position, point)
        turning_time = abs(angle_delta(agent.facing, desired)) / (self.turn_speed * agent.mobility)
        if not self._turn(agent, desired, dt):
            if not agent.alive:
                return self._finish(agent, world, False, "Ciało przestało działać.")
            return None
        distance = min(agent.movement_speed * max(0., dt - turning_time), math.dist(agent.position, point))
        destination = agent.facing.ahead(agent.position, distance)
        if not world.clear_segment(agent.position, destination, agent.radius, (agent.id,)):
            self.path.clear()
            # Contact supplies only the obstacle actually touched, never the full arena.
            for o in world.solids((agent.id,)):
                if segment_distance(o.position, agent.position, destination) < agent.radius + o.radius:
                    self.obstacles[o.id] = (o.position, o.radius)
            if self.replans > 12:
                return self._finish(agent, world, False, "Droga pozostaje zablokowana; zatrzymałam się przed przeszkodą.")
            if not world.inside(destination, agent.radius):
                return self._finish(agent, world, False, "Zatrzymałam się przy granicy areny.")
            return None
        if not agent.spend_energy(distance * ENERGY.move_per_metre, "Brak energii na chodzenie."):
            return self._finish(agent, world, False, "Ciało przestało działać podczas chodzenia.")
        agent.position = destination
        self.travelled += distance
        agent.fatigue = min(100, agent.fatigue + distance * .5)
        if math.dist(agent.position, point) < .001:
            self.path.pop(0)
        return None
