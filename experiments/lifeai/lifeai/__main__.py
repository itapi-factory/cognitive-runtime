from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from .brain import BrainError
from .config import Settings
from .simulation import Simulation, run_headless


def main() -> None:
    parser = argparse.ArgumentParser(description="LifeAI · symulacja istoty sterowanej przez lokalny LLM")
    parser.add_argument("--base-url", help="Adres API kompatybilnego z OpenAI, łącznie z /v1")
    parser.add_argument("--model", help="Nazwa modelu w API; domyślnie automatyczne wykrywanie")
    parser.add_argument("--seed", type=int, help="Ziarno generatora areny")
    parser.add_argument("--agents", dest="agent_count", type=int, help="Liczba autonomicznych istot: 1–8")
    parser.add_argument("--memory-budget", type=int, help="Limit pamięci: 600–32000 szac. tokenów (domyślnie 8000)")
    parser.add_argument("--thinking-interval", type=float, help="Odstęp analiz podczas działania: 0,1–60 s (domyślnie 3)")
    parser.add_argument("--load", type=Path, help="Wczytaj zapisaną sesję")
    parser.add_argument("--save", type=Path, default=Path("data/last_session.json"))
    parser.add_argument("--check-llm", action="store_true", help="Sprawdź /models i rzeczywistą decyzję modelu")
    parser.add_argument("--headless", action="store_true", help="Uruchom bez okna, z rzeczywistym LLM")
    parser.add_argument("--steps", type=int, default=30, help="Liczba działań w trybie bez okna")
    parser.add_argument("--sleep-at", type=int, help="Wymuś sen po N działaniach w trybie bez okna")
    parser.add_argument("--screenshot", type=Path, help="Zapisz widok Pygame; z --headless po symulacji")
    args = parser.parse_args()
    if args.steps < 0 or (args.sleep_at is not None and args.sleep_at < 0):
        parser.error("Liczba działań nie może być ujemna.")
    sim = None
    try:
        settings = Settings.from_env()
        overrides = {
            key: getattr(args, key) for key in ("base_url", "model", "seed", "memory_budget", "agent_count", "thinking_interval")
            if getattr(args, key) is not None
        }
        settings = replace(settings, **overrides)
        sim = Simulation.load(args.load, settings) if args.load else Simulation(settings)
        if args.check_llm:
            brain = sim.brain
            brain.discover()
            sim.agent.look(sim.world)
            plan = brain.plan(sim.agent.snapshot(settings.max_plan))
            print(json.dumps({
                "model": brain.model, "root": brain.model_root,
                "goal": plan.goal, "actions": plan.actions, "metrics": brain.last_metrics,
            }, ensure_ascii=False, indent=2))
            return
        sim.enable_journal(args.save.parent / "journals")
        if args.headless:
            try:
                report = run_headless(sim, args.steps, args.sleep_at)
            finally:
                sim.save(args.save)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.screenshot or not args.headless:
            if args.headless or args.screenshot:
                os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
            from .ui import App
            app = App(sim, args.save)
            if args.screenshot:
                import pygame
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                pygame.image.save(app.draw(), str(args.screenshot))
                pygame.quit()
            else:
                app.run()
    except (BrainError, ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"LifeAI: {exc}\n")
    finally:
        if sim:
            sim.close()


if __name__ == "__main__":
    main()
