from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path

import pygame

from .simulation import Simulation
from .brain import render_context, ACTION_LABELS
from .conversation import dialogue_label
from .world import Corpse, Heading

BG = (12, 17, 26)
PANEL = (19, 27, 39)
BORDER = (37, 50, 65)
TEXT = (228, 237, 244)
MUTED = (135, 153, 173)
MINT = (105, 229, 190)
BLUE = (100, 171, 249)
PURPLE = (181, 155, 245)
AMBER = (243, 193, 113)
RED = (251, 131, 139)

PHASES = {
    "observe": "OBSERWACJA", "thinking": "ANALIZA LLM", "acting": "DZIAŁANIE",
    "sleeping": "SEN / RETROSPEKCJA", "waking": "PRZEBUDZENIE",
    "talking": "ROZMOWA / OPOWIEŚĆ",
    "retrying": "PONAWIANIE LLM", "error": "BŁĄD POŁĄCZENIA", "dead": "ŚMIERĆ / PAMIĘĆ USUNIĘTA",
}


class App:
    SIZE = (1440, 980)

    def __init__(self, simulation: Simulation, save_path: Path = Path("data/last_session.json")):
        # No mixer: the simulation doesn't need audio or access to an audio device.
        pygame.display.init()
        pygame.font.init()
        desktop_w, desktop_h = pygame.display.get_desktop_sizes()[0]
        window_size = (min(1440, max(720, desktop_w - 80)), min(980, max(490, desktop_h - 100)))
        self.screen = pygame.display.set_mode(window_size, pygame.RESIZABLE)
        pygame.display.set_caption("LifeAI · ucieleśniony agent LLM")
        self.canvas = pygame.Surface(self.SIZE)
        self.sim = simulation
        self.focus_id = simulation.agent.id
        self.save_path = save_path
        self.clock = pygame.time.Clock()
        self.fonts = {}
        self.buttons: list[tuple[pygame.Rect, str]] = []
        self.view = 0
        self.tab = "Myśli"
        self.scroll = 0
        self.scroll_max = 0
        self.notice = ""
        self.notice_until = 0.0
        self.running = True
        self.board_rect = pygame.Rect(71, 151, 725, 609)
        self.scale = min(self.board_rect.width / simulation.world.width,
                         self.board_rect.height / simulation.world.height)
        self.memory_cache_key = None
        self.memory_cache = None
        self.journal_layout_agent = None
        self.journal_layouts = []
        self.saved_deaths: set[str] = set()

    @property
    def focused(self) -> Simulation:
        return self.sim.controllers.get(self.focus_id, self.sim)

    def font(self, size: int = 18, bold: bool = False) -> pygame.font.Font:
        key = size, bold
        if key not in self.fonts:
            self.fonts[key] = pygame.font.SysFont("Aptos,DejaVu Sans,Arial", size, bold=bold)
        return self.fonts[key]

    def text(self, value: str, pos: tuple, color=TEXT, size=18, bold=False, surface=None) -> None:
        (surface or self.canvas).blit(self.font(size, bold).render(str(value), True, color), pos)

    def wrapped(self, value: str, x: int, y: int, width: int, color=TEXT,
                size=18, max_lines: int = 99, surface=None, measure=False) -> int:
        font = self.font(size)
        lines = []
        for paragraph in str(value).splitlines() or [""]:
            line = ""
            for word in paragraph.split():
                # Long endpoint names / serialized values must not escape a panel.
                chunks = []
                chunk = ""
                for char in word:
                    if font.size(chunk + char)[0] > width and chunk:
                        chunks.append(chunk)
                        chunk = ""
                    chunk += char
                chunks.append(chunk)
                for part in chunks:
                    candidate = f"{line} {part}".strip()
                    if font.size(candidate)[0] > width and line:
                        lines.append(line)
                        line = part
                    else:
                        line = candidate
            lines.append(line)
        overflow = len(lines) > max_lines
        lines = lines[:max_lines]
        if overflow and lines:
            lines[-1] = lines[-1].rstrip(" .") + "…"
            while font.size(lines[-1])[0] > width:
                lines[-1] = lines[-1][:-2] + "…"
        for line in lines:
            if not measure:
                self.text(line, (x, y), color, size, surface=surface)
            y += font.get_linesize() + 3
        return y

    def card(self, rect: pygame.Rect) -> None:
        pygame.draw.rect(self.canvas, PANEL, rect, border_radius=16)
        pygame.draw.rect(self.canvas, BORDER, rect, width=1, border_radius=16)

    def button(self, rect: pygame.Rect, label: str, action: str, selected=False) -> None:
        pygame.draw.rect(self.canvas, (37, 61, 65) if selected else (29, 40, 54), rect, border_radius=8)
        color = MINT if selected else TEXT
        rendered = self.font(15, selected).render(label, True, color)
        self.canvas.blit(rendered, rendered.get_rect(center=rect.center))
        self.buttons.append((rect, action))

    def bar(self, y: int, label: str, value: float, maximum: float, color, suffix="") -> None:
        self.text(label, (884, y), MUTED, 15)
        amount = f"{value:.0f} / {maximum:.0f}{suffix}"
        rendered = self.font(15).render(amount, True, TEXT)
        self.canvas.blit(rendered, (1392 - rendered.get_width(), y))
        track = pygame.Rect(1000, y + 5, 220, 8)
        pygame.draw.rect(self.canvas, BORDER, track, border_radius=4)
        fill = track.copy()
        fill.width = max(0, min(track.width, round(track.width * value / maximum)))
        if fill.width:
            pygame.draw.rect(self.canvas, color, fill, border_radius=4)

    def draw_header(self) -> None:
        self.text("LIFE", (26, 23), TEXT, 30, True)
        self.text("AI", (99, 23), MINT, 30, True)
        self.text("Laboratorium ucieleśnionej inteligencji", (160, 23), TEXT, 20)
        self.text("Obserwuj. Poznawaj. Zapamiętuj. Śnij.", (160, 49), MUTED, 15)
        self.button(pygame.Rect(862, 24, 130, 40),
                    "Wznów  /  spacja" if self.sim.paused else "Pauza  /  spacja", "pause")
        self.button(pygame.Rect(1002, 24, 118, 40), "Sen  /  D", "sleep")
        self.button(pygame.Rect(1130, 24, 125, 40), "Zapis  /  S", "save")
        self.button(pygame.Rect(1265, 24, 151, 40),
                    "Ponów LLM  /  B" if self.focused.error else "Nowa arena  /  R",
                    "retry" if self.focused.error else "reset")

    def draw_world(self) -> None:
        sim, agent = self.focused, self.focused.agent
        self.card(pygame.Rect(24, 92, 820, 704))
        self.text("01  /  ARENA", (45, 111), TEXT, 16, True)
        self.button(pygame.Rect(216, 105, 134, 30), "Nowa istota / N", "companion")
        self.button(pygame.Rect(360, 105, 135, 30), f"Istota / Tab  {len(sim.controllers)}", "next_agent")
        self.button(pygame.Rect(506, 105, 143, 30), "Pełny świat", "world", self.view == 0)
        self.button(pygame.Rect(658, 105, 164, 30), "Wzrok istoty", "memory", self.view == 1)
        self.scale = min(self.board_rect.width / sim.world.width, self.board_rect.height / sim.world.height)
        pygame.draw.rect(self.canvas, (15, 23, 32), self.board_rect, border_radius=8)
        pygame.draw.rect(self.canvas, BORDER, self.board_rect, 2, border_radius=8)
        visible = {c.id for c in agent.visible}
        if agent.alive:
            origin = self.world_pixel(agent.position)
            fan = [origin]
            solids = sim.world.solids((agent.id,))
            for offset in range(-45, 46, 2):
                direction = Heading(agent.facing + offset)
                # Observer rendering ray cast; this geometry is never sent to the LLM.
                dx, dy = direction.vector
                distance = agent.vision_range
                for axis, component in enumerate((dx, dy)):
                    if abs(component) > 1e-9:
                        boundary = (sim.world.width, sim.world.height)[axis] if component > 0 else 0
                        distance = min(distance, max(0, (boundary - agent.position[axis]) / component))
                for obj in solids:
                    ox, oy = obj.position[0] - agent.position[0], obj.position[1] - agent.position[1]
                    projection = ox * dx + oy * dy
                    perpendicular2 = ox * ox + oy * oy - projection * projection
                    if projection > 0 and perpendicular2 < obj.radius ** 2:
                        distance = min(distance, max(0, projection - math.sqrt(obj.radius ** 2 - perpendicular2)))
                fan.append(self.world_pixel(direction.ahead(agent.position, distance)))
            pygame.draw.polygon(self.canvas, (26, 49, 54), fan)
        old_clip = self.canvas.get_clip()
        self.canvas.set_clip(self.board_rect)
        for obj in sim.world.objects.values():
            if self.view == 1 and obj.id not in visible:
                continue
            point = self.world_pixel(obj.position)
            radius = max(3, round(obj.radius * self.scale))
            if obj.kind == "food":
                pygame.draw.circle(self.canvas, AMBER, point, radius)
                pygame.draw.line(self.canvas, MINT, (point[0], point[1] - radius),
                                 (point[0] + 4, point[1] - radius - 4), 2)
            else:
                pygame.draw.circle(self.canvas, (87, 103, 120), point, radius)
                pygame.draw.circle(self.canvas, (119, 134, 149), point, radius, 2)
            if obj.id in visible:
                pygame.draw.circle(self.canvas, (61, 114, 109), point, radius + 4, 1)
        if agent.motor and agent.motor.action not in ("look", "wait"):
            points = [self.world_pixel(agent.position)] + [self.world_pixel(p) for p in agent.motor.path]
            if len(points) > 1:
                pygame.draw.lines(self.canvas, (80, 125, 132), False, points, 1)
            pygame.draw.circle(self.canvas, BLUE, self.world_pixel(agent.motor.goal), 6, 1)
        for other in sim.world.entities.values():
            if self.view == 0 or other is agent or other.id in visible:
                if isinstance(other, Corpse):
                    self.draw_corpse(other)
                else:
                    self.draw_creature(other)
        self.canvas.set_clip(old_clip)
        self.text(f"Świat ciągły {sim.world.width:g} × {sim.world.height:g} m  ·  wzrok {agent.vision_range} m / 90°",
                  (45, 771), MUTED, 13)
        if self.view == 1:
            self.text("Tylko bieżący wzrok", (661, 771), PURPLE, 14)

    def world_pixel(self, position):
        return (round(self.board_rect.x + position[0] * self.scale),
                round(self.board_rect.y + position[1] * self.scale))

    def draw_corpse(self, corpse: Corpse) -> None:
        cx, cy = self.world_pixel(corpse.position)
        pygame.draw.ellipse(self.canvas, (74, 77, 89), (cx - 12, cy - 7, 24, 14))
        for offset in (-5, 5):
            pygame.draw.line(self.canvas, TEXT, (cx + offset - 2, cy - 3), (cx + offset + 2, cy + 1), 2)
            pygame.draw.line(self.canvas, TEXT, (cx + offset - 2, cy + 1), (cx + offset + 2, cy - 3), 2)
        self.text(corpse.name, (cx - 14, cy + 13), MUTED, 10)

    def draw_creature(self, agent) -> None:
        cx, cy = self.world_pixel(agent.position)
        fx, fy = agent.facing.vector
        sx, sy = -fy, fx

        def local(forward, side):
            return round(cx + fx * forward + sx * side), round(cy + fy * forward + sy * side)

        controller = self.sim.controllers.get(agent.id)
        asleep = controller is not None and controller.phase == "sleeping"
        color = PURPLE if asleep else (
            (MINT if agent is self.focused.agent else BLUE) if agent.alive else RED)
        pygame.draw.circle(self.canvas, (34, 77, 76), (cx, cy), 16, 2)
        pygame.draw.polygon(self.canvas, color, [local(22, 0), local(15, -4), local(15, 4)])
        pygame.draw.circle(self.canvas, color, (cx, cy), 12)
        for side in (-4.5, 4.5):
            eye = local(3, side)
            if not agent.alive:
                pygame.draw.line(self.canvas, BG, (eye[0] - 2, eye[1] - 2), (eye[0] + 2, eye[1] + 2), 2)
                pygame.draw.line(self.canvas, BG, (eye[0] - 2, eye[1] + 2), (eye[0] + 2, eye[1] - 2), 2)
            elif asleep:
                pygame.draw.line(self.canvas, BG, (eye[0] - 2, eye[1]), (eye[0] + 2, eye[1]), 2)
            else:
                pygame.draw.circle(self.canvas, (245, 255, 253), eye, 4)
                pygame.draw.circle(self.canvas, BG, local(4.5, side), 2)
        # Mouth sits below the pair of eyes on the creature's face, toward the front.
        pygame.draw.line(self.canvas, (18, 76, 64), local(9, -3), local(9, 3), 2)
        if asleep:
            self.text("z Z", (cx + 15, cy - 31), PURPLE, 18, True)
        elif controller and controller.phase == "talking":
            self.text("…", (cx + 15, cy - 28), BLUE, 22, True)
        if len(self.sim.controllers) > 1:
            self.text(agent.name, (cx - 14, cy + 17), color, 11)

    def draw_body(self) -> None:
        agent = self.focused.agent
        self.card(pygame.Rect(862, 92, 554, 166))
        self.text(f"{agent.name.upper()}  /  {agent.id}", (884, 108), TEXT, 18, True)
        self.text(f"({agent.position[0]:.2f}, {agent.position[1]:.2f}) · {float(agent.facing):.1f}°",
                  (1160, 111), MUTED, 15)
        self.bar(145, "Energia", agent.energy, 100, MINT if agent.energy > 25 else RED)
        self.bar(177, "Zmęczenie", agent.fatigue, 100, PURPLE)
        self.bar(209, "Pamięć ≈ tok.", agent.memory.used, agent.memory.budget,
                 AMBER if agent.memory.ratio >= 0.7 else BLUE)
        self.text(f"Polecenia: {agent.age}  •  Posiłki: {agent.meals}  •  "
                  f"Życie: {agent.lifetime_seconds:.0f} s  •  Koszt: {self.focused.energy_per_second:.2f} E/s",
                  (884, 236), MUTED, 13)

    def draw_brain(self) -> None:
        sim, agent = self.focused, self.focused.agent
        self.card(pygame.Rect(862, 272, 554, 244))
        color = RED if sim.error or not agent.alive else PURPLE if sim.phase == "sleeping" else MINT
        pulse = 4 + round(math.sin(time.monotonic() * 4)) if sim.pending else 4
        pygame.draw.circle(self.canvas, color, (889, 297), pulse)
        phase = "PAUZA" if sim.paused and agent.alive else PHASES.get(sim.phase, sim.phase)
        if not sim.paused and sim.phase == "retrying" and sim.retry_is_validation:
            phase = "KOREKTA PLANU LLM"
        if agent.motor and not sim.paused and sim.phase in ("thinking", "retrying", "talking"):
            phase += " + CIAŁO"
        self.text(phase, (904, 285), color, 16, True)
        latency = f"{time.monotonic() - sim.request_started:.1f} s" if sim.pending else (
            f"{sim.brain.last_metrics.get('seconds', 0):.2f} s / LLM"
        )
        self.text(latency, (1284, 287), MUTED, 14)
        if sim.error:
            self.wrapped(sim.error, 884, 322, 508, RED, 16, 5)
            if agent.motor:
                self.wrapped("Ciało nadal działa: " + agent.motor.status, 884, 445, 508, BLUE, 13, 2)
            self.text(f"Automatyczna próba {sim.retry_count + 1} za {max(0, sim.retry_at - time.monotonic()):.0f} s. Spacja: pauza.", (884, 484), MUTED, 14)
            return
        if sim.phase == "dead":
            self.wrapped("Energia spadła do zera. Istota umarła. "
                         "Jej myśli, wspomnienia i plany przestały istnieć. "
                         "R tworzy nową istotę z pustą pamięcią.",
                         884, 326, 508, RED, 19, 5)
            return
        if sim.phase == "sleeping":
            self.wrapped("Porządkuję doświadczenia.", 884, 326, 508, TEXT, 22, 1)
            self.wrapped(sim.sleep_reason, 884, 367, 508, MUTED, 17, 2)
            self.wrapped("LLM wybiera wspomnienia do wzmocnienia, osłabia pozostałe "
                         "i zapisuje wnioski na kolejny dzień.", 884, 426, 508, PURPLE, 17, 3)
            return
        if sim.phase == "talking":
            listener = sim.controllers.get(agent.talk_target)
            name = listener.agent.name if listener else "inna istota"
            reply = sim.last_prompt.get("reply_to")
            self.wrapped(f"{'Odpowiadam' if reply else 'Mówię'} do: {name}", 884, 326, 508, BLUE, 22, 2)
            self.wrapped(('Usłyszana kwestia: „' + reply['text'] + '”') if reply else
                         "Przekazuję przeżycia i pytania własnymi słowami. Po wypowiedzi oddam kolej rozmówcy.",
                         884, 399, 508, MUTED, 18, 4)
            return
        self.wrapped(agent.goal, 884, 325, 508, TEXT, 21, 2)
        self.wrapped(agent.intent, 884, 386, 508, MUTED, 17, 3)
        if agent.motor:
            self.wrapped("Ciało: " + agent.motor.status, 884, 445, 508, BLUE, 13, 1)
        else:
            dialogue = agent.dialogue.snapshot()
            status = ("Rozmowa: jest kwestia do rozważenia" if dialogue['incoming'] else
                      "Rozmowa: czekam na reakcję" if dialogue['awaiting_reply'] else
                      "Ciało: brak wykonywanego polecenia")
            self.text(status, (884, 445), BLUE if dialogue['incoming'] else MUTED, 13)
        x = 884
        commands = ([agent.motor.command] if agent.motor else []) + list(agent.plan)
        for i, command in enumerate(commands[:3]):
            label = ACTION_LABELS[command["action"]]
            width = self.font(14).size(label)[0] + 16
            if x + width > 1392:
                break
            pygame.draw.rect(self.canvas, (32, 57, 61) if i == 0 else (29, 39, 54),
                             (x, 474, width, 27), border_radius=6)
            self.text(label, (x + 8, 478), MINT if i == 0 else MUTED, 14)
            x += width + 7
        if not commands:
            self.text("Obserwacja → zamiar LLM → autonomiczne wykonanie", (884, 478), MUTED, 14)

    def draw_memory(self) -> None:
        sim, memory = self.focused, self.focused.agent.memory
        self.card(pygame.Rect(862, 530, 554, 402))
        for i, label in enumerate(("Myśli", "Wrażenia", "Rozmowy", "Kontekst", "Dziennik")):
            self.button(pygame.Rect(882 + i * 104, 545, 99, 33), label, "tab:" + label, self.tab == label)
        if self.tab == "Dziennik":
            self.draw_journal()
            return
        if not sim.agent.alive:
            self.memory_cache = self.memory_cache_key = None
            self.scroll = self.scroll_max = 0
            self.wrapped("Ta perspektywa zgasła. Pozostało ciało, a jej pamięć już nie istnieje.",
                         884, 596, 508, MUTED, 18)
            return
        key = (id(memory), self.tab, memory.next_id, memory.sleeps, memory.forgotten,
               id(sim.last_prompt), sim.phase, sim.paused,
               tuple((n.id, n.text) for n in memory.nodes if n.experience),
               tuple((n.id, n.utterance['state']) for n in sim.agent.dialogue.rows()))
        if key == self.memory_cache_key:
            self.draw_memory_view(*self.memory_cache)
            return
        context = render_context(sim.last_prompt) if sim.last_prompt else "Jeszcze nie było analizy."
        height = max(6000, (len(context) + len(memory.context())) * 2)
        content = pygame.Surface((508, min(100000, height)))
        content.fill(PANEL)
        y = 0
        if self.tab == "Kontekst":
            self.text("TAKI TEKST CZYTA MODEL", (0, y), BLUE, 13, True, surface=content)
            y = self.wrapped(context, 0, y + 28, 495, TEXT, 16, max_lines=10000, surface=content)
        elif self.tab == "Wrażenia":
            y = self.wrapped("Bieżące odczucia czekające na interpretację. Nie są jeszcze wnioskami.",
                             0, y, 495, MUTED, 16, surface=content) + 20
            for item in memory.impressions:
                y = self.wrapped(item.text, 0, y, 495, TEXT, 17, surface=content) + 22
        else:
            nodes = [n for n in memory.nodes if self.tab != "Rozmowy" or n.origins or n.audience or n.source == "spoken"]
            if not nodes:
                y = self.wrapped("Moje spostrzeżenia powstaną w czasie poznawania świata." if self.tab == "Myśli"
                                 else "Jeszcze nie pamiętam spotkania, które przerodziło się w rozmowę.",
                                 0, 0, 495, MUTED, 18, surface=content)
            if self.tab == "Myśli" and nodes:
                recent = nodes[-8:]
                positions = {n.id: (40 + i % 4 * 130, 25 + i // 4 * 65) for i, n in enumerate(recent)}
                for n in recent:
                    for link in n.links:
                        if link in positions:
                            pygame.draw.line(content, BORDER, positions[n.id], positions[link], 2)
                for n in recent:
                    point = positions[n.id]
                    pygame.draw.circle(content, BLUE if n.origins else MINT, point, 14, 2)
                    self.text(str(n.id), (point[0] - 8, point[1] - 8), TEXT, 12, surface=content)
                y = 130 if len(recent) > 4 else 70
            for node in reversed(nodes):
                source = ("OD: " + ", ".join(node.origins.values())) if node.origins else "MOJE SPOSTRZEŻENIE"
                if node.source == "observation":
                    source = "ZAPAMIĘTANY WIDOK"
                if node.experience:
                    source = {"active": "MÓJ ZAMIAR I PRZEWIDYWANIE", "queued": "KOLEJNY ZAMIAR",
                              "ready": "PRÓBA · WYNIK DO ROZWAŻENIA",
                              "reviewed": "PRÓBA · ROZWAŻONY WYNIK"}[node.experience["state"]]
                if node.source == "spoken":
                    source = "DO: " + (", ".join(node.audience.values()) or "INNEJ ISTOTY")
                self.text(f"{source} · {node.id}", (0, y), BLUE if node.origins else MINT, 12, True, surface=content)
                y = self.wrapped(node.text, 0, y + 24, 495, TEXT, 18, surface=content) + 10
                if node.utterance:
                    y = self.wrapped(dialogue_label(node.utterance), 0, y, 495, BLUE, 13, surface=content) + 10
                if node.links:
                    y = self.wrapped("Łączy się z myślami: " + ", ".join(map(str, node.links)),
                                     0, y, 495, MUTED, 13, surface=content) + 8
                y += 18
            if self.tab == "Myśli" and memory.last_sleep:
                self.text("PO OSTATNIM ŚNIE", (0, y), PURPLE, 13, True, surface=content)
                y = self.wrapped(memory.last_sleep["reflection"], 0, y + 26, 495, TEXT, 17, surface=content)
        self.memory_cache_key, self.memory_cache = key, (content, y)
        self.draw_memory_view(content, y)

    def draw_journal(self) -> None:
        sim = self.focused
        if self.journal_layout_agent is not sim or len(self.journal_layouts) > len(sim.events):
            self.journal_layout_agent, self.journal_layouts = sim, []
        events = list(sim.events)
        for event in events[len(self.journal_layouts):]:
            text = event['text']
            if event.get('thought'):
                text += '\nSpostrzeżenie: ' + event['thought']
            if event.get('expectation'):
                text += '\nPrzewidywanie przed próbą: ' + event['expectation']
            if event.get('actions'):
                text += '\nPlan: ' + ', '.join(ACTION_LABELS.get(a.get('action'), a.get('action', '?')) if isinstance(a, dict) else a for a in event['actions'])
            if event.get('control'):
                controls = {'continue': 'kontynuacja', 'queue': 'nowa kolejka',
                            'replace': 'zmiana czynności', 'stop': 'zatrzymanie'}
                text += '\nDecyzja: ' + controls.get(event['control'], event['control'])
            if event.get('decision_note'):
                text += '\nNie zastosowano polecenia: ' + event['decision_note']
            if event.get('in_reply_to'):
                text += '\nOdpowiedź na wypowiedź: ' + event['in_reply_to']
            body, before = event.get('body', {}), event.get('before')
            if body:
                text += f"\nPozycja {body['position']} · energia {body['energy']:.2f}"
                if before:
                    text += f" (przed: {before['energy']:.2f})"
            if event.get('reason'):
                text += '\nPrzyczyna: ' + event['reason']
            height = self.wrapped(text, 0, 0, 495, size=16, max_lines=10000, measure=True) + 54
            self.journal_layouts.append((event, text, height))
        total = sum(item[2] for item in self.journal_layouts) + 34
        self.scroll_max = max(0, total - 312 + 8)
        self.scroll = max(0, min(self.scroll, self.scroll_max))
        # Render only the visible viewport, even for very long sessions.
        content = pygame.Surface((508, 312))
        content.fill(PANEL)
        label = 'ARCHIWUM OBSERWATORA' if sim.journal.history_complete else 'ARCHIWUM · STARSZA HISTORIA NIEPEŁNA'
        self.text(label, (0, -self.scroll), MUTED, 12, True, surface=content)
        y = 34
        for event, text, height in reversed(self.journal_layouts):
            if y > self.scroll + 312:
                break
            if y + height >= self.scroll:
                top = y - self.scroll
                color = RED if event['kind'] in ('death', 'error') else BLUE if event['kind'] == 'talk' else MINT
                self.text(f"#{event.get('sequence', '?')} · t={event['tick']} · {event['title']}",
                          (0, top), color, 12, True, surface=content)
                self.wrapped(text, 0, top + 24, 495, TEXT, 16, max_lines=10000, surface=content)
            y += height
        self.draw_memory_view(content, total, viewport_only=True)

    def draw_memory_view(self, content: pygame.Surface, y: int, *, viewport_only=False) -> None:
        view = pygame.Rect(884, 596, 508, 312)
        self.scroll_max = max(0, y - view.height + 8)
        self.scroll = max(0, min(self.scroll, self.scroll_max))
        self.canvas.blit(content, view, (0, 0 if viewport_only else self.scroll, view.width, view.height))
        if self.scroll_max:
            track = pygame.Rect(1400, view.y, 4, view.height)
            pygame.draw.rect(self.canvas, BORDER, track, border_radius=2)
            thumb = max(25, round(view.height * view.height / (y + 8)))
            offset = round((view.height - thumb) * self.scroll / self.scroll_max)
            pygame.draw.rect(self.canvas, MUTED, (1400, view.y + offset, 4, thumb), border_radius=2)
        self.text("Kółko myszy: przewijanie", (1223, 914), MUTED, 11)

    def draw_log(self) -> None:
        self.card(pygame.Rect(24, 810, 820, 122))
        self.text("DZIENNIK OBSERWATORA", (44, 825), MUTED, 12, True)
        self.text(f"cykl {self.focused.cycles:03}  /  czas świata {self.sim.world.tick:04}",
                  (558, 824), MUTED, 13)
        for i, event in enumerate(reversed(list(self.focused.events)[-3:])):
            color = {"sleep": PURPLE, "plan": BLUE, "eat": AMBER, "error": RED,
                     "death": RED, "talk": BLUE}.get(event["kind"], MINT)
            self.text(f"{event['tick']:04}", (44, 852 + i * 24), MUTED, 13)
            self.wrapped(event["text"], 94, 850 + i * 24, 724, color, 15, 1)

    def draw_footer(self) -> None:
        message = self.notice if time.monotonic() < self.notice_until else (
            "Tab / klik istoty: wybór    N: nowa istota    G: widok    D: sen    S: zapis    "
            "+/−: tempo    Klik / PPM: jedzenie"
        )
        if self.sim.journal.error:
            message = "Błąd zapisu dziennika: " + self.sim.journal.error
        self.text(message, (26, 951), MINT if time.monotonic() < self.notice_until else MUTED, 14)
        speed = f"{0.65 / self.sim.action_delay:.1f}×" if self.sim.action_delay else "test"
        self.text(f"{speed}   ·   lokalny LLM", (1242, 951), MUTED, 14)

    def draw(self) -> pygame.Surface:
        self.buttons.clear()
        self.canvas.fill(BG)
        self.draw_header()
        self.draw_world()
        self.draw_body()
        self.draw_brain()
        self.draw_memory()
        self.draw_log()
        self.draw_footer()
        size = self.screen.get_size()
        ratio = min(size[0] / self.SIZE[0], size[1] / self.SIZE[1])
        scaled = pygame.transform.smoothscale(self.canvas, (int(1440 * ratio), int(980 * ratio)))
        self.screen.fill(BG)
        self.screen.blit(scaled, ((size[0] - scaled.get_width()) // 2, (size[1] - scaled.get_height()) // 2))
        pygame.display.flip()
        return self.canvas

    def virtual_pos(self, pos: tuple[int, int]) -> tuple[int, int]:
        w, h = self.screen.get_size()
        ratio = min(w / 1440, h / 980)
        return round((pos[0] - (w - 1440 * ratio) / 2) / ratio), round((pos[1] - (h - 980 * ratio) / 2) / ratio)

    def notify(self, text: str) -> None:
        self.notice, self.notice_until = text, time.monotonic() + 5

    def dispatch(self, action: str) -> None:
        if action == "pause":
            self.sim.paused = not self.sim.paused
        elif action == "sleep":
            self.focused.request_sleep()
            self.notify("Zaplanowano sen; odpoczynek i pamięć zużyją energię."
                        if self.focused.agent.alive else "Martwa istota nie może zasnąć.")
        elif action == "save":
            try:
                self.sim.save(self.save_path)
                self.notify(f"Zapisano: {self.save_path}")
            except OSError as exc:
                self.notify(f"Błąd zapisu: {exc}")
        elif action == "retry":
            self.focused.retry()
        elif action == "reset":
            journal_directory = self.sim.journal.directory
            try:
                self.sim.save(self.save_path)
            except OSError as exc:
                self.notify(f"Nie udało się zapisać kończonej sesji: {exc}")
                return
            self.sim.close()
            self.sim = Simulation(replace(self.sim.settings, seed=self.sim.world.seed + 1))
            if journal_directory is not None:
                try:
                    self.sim.enable_journal(journal_directory)
                except OSError as exc:
                    self.notify(f"Błąd dziennika: {exc}")
            self.focus_id = self.sim.agent.id
            self.scroll = 0
            self.saved_deaths.clear()
        elif action == "companion":
            try:
                companion = self.sim.add_companion(near=self.focused.agent)
                self.notify(f"Na arenie pojawia się {companion.agent.name}. Tab zmienia obserwowaną istotę.")
            except ValueError as exc:
                self.notify(str(exc))
        elif action == "next_agent":
            ids = list(self.sim.controllers)
            self.focus_id = ids[(ids.index(self.focus_id) + 1) % len(ids)]
            self.scroll = 0
        elif action == "world":
            self.view = 0
        elif action == "memory":
            self.view = 1
        elif action.startswith("tab:"):
            self.tab, self.scroll = action[4:], 0
        elif action in ("faster", "slower"):
            delay = max(0.10, min(2.6, self.sim.action_delay * (0.5 if action == "faster" else 2)))
            for controller in self.sim.controllers.values():
                controller.action_delay = delay

    def handle(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.KEYDOWN:
            keys = {
                pygame.K_SPACE: "pause", pygame.K_d: "sleep", pygame.K_s: "save",
                pygame.K_r: "reset", pygame.K_b: "retry", pygame.K_EQUALS: "faster",
                pygame.K_PLUS: "faster", pygame.K_KP_PLUS: "faster",
                pygame.K_MINUS: "slower", pygame.K_KP_MINUS: "slower",
                pygame.K_n: "companion", pygame.K_TAB: "next_agent",
            }
            if event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_g:
                self.view = 1 - self.view
            elif event.key in keys:
                self.dispatch(keys[event.key])
        elif event.type == pygame.MOUSEWHEEL:
            if self.virtual_pos(pygame.mouse.get_pos())[0] >= 862:
                self.scroll = max(0, min(self.scroll_max, self.scroll - event.y * 50))
        elif event.type == pygame.MOUSEBUTTONDOWN:
            pos = self.virtual_pos(event.pos)
            if event.button == 1:
                for rect, action in self.buttons:
                    if rect.collidepoint(pos):
                        self.dispatch(action)
                        return
            if self.board_rect.collidepoint(pos) and event.button in (1, 3):
                point = ((pos[0] - self.board_rect.x) / self.scale,
                         (pos[1] - self.board_rect.y) / self.scale)
                world = self.sim.world
                occupant = world.occupant(point)
                obj = world.object_at(point, .12)
                if occupant and event.button == 1:
                    self.focus_id = occupant.id
                    self.scroll = 0
                elif occupant is None:
                    if event.button == 1 and obj is None and world.clear_position(point, .18):
                        food = world.add_object("food", point)
                        self.focused.event("Interwencja", f"Obserwator dodał jedzenie przy {point}.", "system",
                                           object=food.to_dict())
                    elif event.button == 3 and obj and obj.kind == "food":
                        del world.objects[obj.id]
                        self.focused.event("Interwencja", f"Obserwator usunął jedzenie {obj.id}.", "system",
                                           object=obj.to_dict())

    def run(self) -> None:
        try:
            while self.running:
                for event in pygame.event.get():
                    self.handle(event)
                self.sim.update()
                deaths = {c.agent.id for c in self.sim.controllers.values() if not c.agent.alive}
                if deaths - self.saved_deaths:
                    self.saved_deaths = deaths
                    self.dispatch("save")
                self.draw()
                self.clock.tick(30)
        finally:
            try:
                self.sim.save(self.save_path)
            except OSError as exc:
                print(f"Nie udało się zapisać sesji: {exc}")
            self.sim.close()
            pygame.quit()
