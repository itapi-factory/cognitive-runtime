import os
import tempfile
import unittest
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame

from lifeai.config import Settings
from lifeai.brain import Plan
from lifeai.simulation import Simulation, run_headless
from lifeai.ui import App
from lifeai.world import Tile
from tests.test_simulation import ScriptedBrain


class InterfaceTests(unittest.TestCase):
    def test_click_adds_food_only_on_empty_unoccupied_ground_and_push_plan_renders(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        app = App(sim)
        self.addCleanup(pygame.quit)
        app.screen = pygame.display.set_mode(app.SIZE)

        def click(position, button=1):
            pos=app.world_pixel(position)
            app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN,pos=pos,button=button))
        sim.world.objects.clear()
        empty=(4.23,5.47)
        click(empty)
        self.assertEqual(len(sim.world.objects),1)
        food=next(iter(sim.world.objects.values()))
        self.assertAlmostEqual(food.position[0],empty[0],delta=.04)
        click(empty);click((0,0));click(sim.agent.position)
        self.assertEqual(len(sim.world.objects),1)
        rock=sim.world.add_object('rock',(8.1,4.7))
        click(rock.position)
        self.assertEqual(len(sim.world.objects),2)
        click(empty,button=3)
        self.assertEqual(len(sim.world.objects),1)
        sim.agent.accept_plan(Plan('Przesunę kamień.','Otworzę przejście.',[{'action':'push','target':rock.id}]))
        sim.phase = "acting"
        self.assertEqual(app.draw().get_size(), app.SIZE)

    def test_render_all_tabs_views_and_user_controls(self):
        sim = Simulation(Settings(), ScriptedBrain())
        run_headless(sim, 10, sleep_at=4)
        with tempfile.TemporaryDirectory() as directory:
            app = App(sim, Path(directory) / "session.json")
            try:
                for view in (0, 1):
                    app.view = view
                    for tab in ("Myśli", "Wrażenia", "Rozmowy", "Kontekst", "Dziennik"):
                        app.dispatch("tab:" + tab)
                        self.assertEqual(app.draw().get_size(), (1440, 980))
                        app.scroll = app.scroll_max
                        app.draw()
                app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
                self.assertTrue(sim.paused)
                app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
                self.assertTrue(sim.sleep_requested)
                app.dispatch("save")
                self.assertTrue(app.save_path.exists())
                app.screen = pygame.display.set_mode((1000, 700), pygame.RESIZABLE)
                app.draw()
                sim.phase, sim.error = "error", "Test niedostępnego serwera."
                app.draw()
                sim.agent.spend_energy(100, "Test śmierci.")
                sim.paused = False
                sim.update()
                for tab in ("Myśli", "Wrażenia", "Kontekst"):
                    app.dispatch("tab:" + tab)
                    app.draw()
                    self.assertIsNone(app.memory_cache)
                app.dispatch('tab:Dziennik')
                app.draw()
                self.assertTrue(app.journal_layouts)
                self.assertEqual(app.journal_layouts[-1][0]['kind'], 'death')
                app.scroll = app.scroll_max
                app.draw()
                app.dispatch("save")
                restored = Simulation.load(app.save_path, Settings(), ScriptedBrain())
                self.assertEqual(restored.phase, "dead")
                self.assertEqual(restored.agent.memory.used, 0)
                restored.close()
                app.dispatch("companion")
                app.dispatch("next_agent")
                self.assertIsNot(app.focused, sim)
                self.assertTrue(app.focused.agent.alive)
                app.dispatch("tab:Rozmowy")
                app.draw()
                first_archive = app.sim.enable_journal(Path(directory) / 'journals')
                old_archive = first_archive.read_bytes()
                old_seed = app.sim.world.seed
                app.dispatch('reset')
                self.assertEqual(app.sim.world.seed, old_seed + 1)
                self.assertNotEqual(app.sim.journal.path, first_archive)
                self.assertEqual(first_archive.read_bytes(), old_archive)
                self.assertTrue(app.sim.journal.path.exists())
                app.sim.close()
            finally:
                sim.close()
                pygame.quit()


if __name__ == "__main__":
    unittest.main()
