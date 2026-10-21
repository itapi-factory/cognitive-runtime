import tempfile
import threading
import time
import unittest
from pathlib import Path

from lifeai.brain import BrainError, Plan
from lifeai.config import Settings
from lifeai.simulation import Simulation, run_headless


class ScriptedBrain:
    """Explicit test double only; the application has no heuristic fallback."""
    model = "test-double"
    last_metrics = {}

    def plan(self, snapshot):
        if snapshot.get("body_activity", {}).get("active"):
            return Plan("Poznaję świat.", "Dokończę obecną czynność.", [], control="continue")
        return Plan("Poznaję świat.", "Obrócę się.", [{"action":"look","angle":(snapshot["self"]["heading_degrees"]+90)%360}, {"action":"wait","seconds":.1}])

    def reflect(self, snapshot):
        ids = snapshot["memory_ids"]
        return f"Porównuję ostatnie doświadczenie z wcześniejszym. Wciąż mam pytania o świat. [[{ids[-1]}]]"



class SimulationTests(unittest.TestCase):
    def test_full_cycle_including_sleep_is_bounded(self):
        sim = Simulation(Settings(), ScriptedBrain())
        try:
            report = run_headless(sim, 14, sleep_at=4)
            self.assertEqual(report["steps"], 14)
            self.assertGreaterEqual(sim.agent.memory.sleeps, 1)
            self.assertLessEqual(sim.agent.memory.used, sim.agent.memory.budget)
        finally:
            sim.close()

    def test_tiny_budget_does_not_cause_endless_sleep_before_moving(self):
        sim = Simulation(Settings(memory_budget=600), ScriptedBrain())
        try:
            run_headless(sim, 12, sleep_at=0)
            self.assertGreater(sim.cycles, 0)
            self.assertLess(sim.agent.memory.sleeps, sim.agent.age)
        finally:
            sim.close()

    def test_network_worker_does_not_block_or_mutate_world_while_paused(self):
        gate = threading.Event()

        class DelayedBrain(ScriptedBrain):
            def plan(self, snapshot):
                gate.wait(timeout=2)
                return super().plan(snapshot)

        sim = Simulation(Settings(), DelayedBrain())
        try:
            started = time.monotonic()
            sim.update()
            self.assertLess(time.monotonic() - started, 0.25)
            self.assertEqual(sim.world.tick, 0)
            sim.paused = True
            gate.set()
            time.sleep(0.02)
            sim.update()
            self.assertEqual(sim.world.tick, 0)
            self.assertEqual(sim.phase, "thinking")
            sim.paused = False
            sim.update()
            self.assertEqual(sim.phase, "acting")
        finally:
            gate.set()
            sim.close()

    def test_llm_failure_is_retried_without_human_or_physical_side_effects(self):
        class BrokenOnce(ScriptedBrain):
            calls = 0
            def plan(self, snapshot):
                self.calls += 1
                if self.calls == 1:
                    raise BrainError("offline")
                return super().plan(snapshot)
        brain = BrokenOnce()
        sim = Simulation(Settings(), brain)
        self.addCleanup(sim.close)
        sim.update(0)
        with self.assertRaises(BrainError):
            sim.pending.result(timeout=2)
        sim.update(0)
        self.assertEqual(sim.phase, "retrying")
        self.assertEqual(sim.world.tick, 0)
        energy = sim.agent.energy
        sim.update(0.5)
        self.assertEqual(brain.calls, 1)
        sim.update(1)
        sim.pending.result(timeout=2)
        sim.update(1)
        self.assertEqual(brain.calls, 2)
        self.assertEqual(sim.phase, "acting")
        self.assertLess(sim.agent.energy, energy)
        self.assertEqual(sim.world.tick, 0)

    def test_save_load_restores_world_rng_and_agent_memories(self):
        sim = Simulation(Settings(), ScriptedBrain())
        try:
            run_headless(sim, 6, sleep_at=3)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "session.json"
                sim.save(path)
                loaded = Simulation.load(path, Settings(), ScriptedBrain())
                self.assertEqual(sim.world.to_dict(), loaded.world.to_dict())
                self.assertEqual(sim.agent.to_dict(), loaded.agent.to_dict())
                self.assertEqual(loaded.phase, "observe")
                self.assertFalse(loaded.agent.plan)
                loaded.close()
        finally:
            sim.close()

    def test_loading_increases_each_budget_without_shrinking_larger_memories(self):
        sim = Simulation(Settings(memory_budget=2400), ScriptedBrain())
        self.addCleanup(sim.close)
        other = sim.add_companion(brain=ScriptedBrain())
        other.agent.memory.budget = 16000
        sim.agent.memory.add_thought('Pamiętam ważne pytanie postawione podczas pierwszego spotkania.', 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            sim.save(path)
            loaded = Simulation.load(path, Settings(), ScriptedBrain())
            self.addCleanup(loaded.close)
            self.assertEqual(loaded.agent.memory.budget, 8000)
            self.assertEqual(loaded.controllers[other.agent.id].agent.memory.budget, 16000)
            self.assertEqual(loaded.agent.memory.context(), sim.agent.memory.context())
            self.assertEqual(Settings(memory_budget=32000).memory_budget, 32000)


if __name__ == "__main__":
    unittest.main()
