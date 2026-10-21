import json
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from lifeai.agent import Agent
from lifeai.brain import BrainError, LocalLLM, Plan
from lifeai.config import Settings
from lifeai.energy import ENERGY
from lifeai.simulation import Simulation
from lifeai.world import Tile
from tests.test_simulation import ScriptedBrain
from tests.test_world_agent import empty_world, execute


def seed_memories(agent):
    agent.memory.remember(1, "UNIQUE_MEMORY_MARKER", 1)
    agent.memory.add_thought("UNIQUE_KNOWLEDGE_MARKER jest zapamiętanym spostrzeżeniem.", 1)
    agent.memory.last_sleep = {"reflection": "UNIQUE_SLEEP_MARKER"}
    agent.goal = "UNIQUE_GOAL_MARKER"
    agent.intent = "UNIQUE_INTENT_MARKER"
    agent.plan.extend([{"action": "go_to", "position": [8, 7]}, {"action": "eat", "target": "food-1"}])


class EnergyTests(unittest.TestCase):
    def test_metabolism_is_frame_rate_independent_and_continues_in_each_phase(self):
        for phase in ("observe", "acting", "thinking", "sleeping", "error"):
            with self.subTest(phase=phase):
                one, many = Agent("one", (7, 7)), Agent("many", (7, 7))
                one.elapse(10, phase)
                for _ in range(100):
                    many.elapse(0.1, phase)
                self.assertAlmostEqual(one.energy, 78 - 10 * ENERGY.per_second(phase))
                self.assertAlmostEqual(one.energy, many.energy)
                self.assertAlmostEqual(one.lifetime_seconds, many.lifetime_seconds)

    def test_pause_does_not_drain_energy_or_charge_paused_time_on_resume(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        sim.phase = "error"  # no automatic actions or HTTP requests
        sim.update(0)
        sim.update(10)
        self.assertAlmostEqual(sim.agent.energy, 76)
        sim.paused = True
        sim.update(1000)
        sim.paused = False
        sim.update(2000)
        self.assertAlmostEqual(sim.agent.energy, 76)
        sim.update(2005)
        self.assertAlmostEqual(sim.agent.energy, 75)

    def test_cognitive_startup_costs_are_charged_before_snapshot(self):
        for kind, cost in (("plan", ENERGY.planning), ("sleep", ENERGY.sleep_start)):
            with self.subTest(kind=kind):
                sim = Simulation(Settings(), ScriptedBrain())
                self.addCleanup(sim.close)
                sim._submit(kind)
                sim.pending.result(timeout=2)
                self.assertAlmostEqual(sim.agent.energy, 78 - cost)
                self.assertAlmostEqual(sim.last_prompt["self"]["energy"], round(78 - cost, 1))
                self.assertNotIn("death_at_zero", sim.last_prompt["self"])
                self.assertNotIn("energy_costs", sim.last_prompt["self"])

    def test_consolidation_is_charged_for_actual_memory_before_compression(self):
        agent, world = Agent("one", (7, 7)), empty_world()
        world.add_agent(agent)
        agent.look(world)
        reflection = ScriptedBrain().reflect(agent.snapshot())
        cost = ENERGY.consolidation_cost(agent.memory.used)
        before = agent.energy
        report = agent.wake(reflection, world)
        self.assertAlmostEqual(agent.energy, before - cost)
        self.assertEqual(report["energy_cost"], round(cost, 3))
        self.assertGreater(cost, 0)


class DeathTests(unittest.TestCase):
    def assert_erased(self, agent):
        self.assertTrue(agent.dead)
        self.assertFalse(agent.alive)
        self.assertEqual(agent.energy, 0)
        self.assertTrue(agent.memory.erased)
        self.assertEqual(agent.memory.context(), "")
        self.assertEqual(agent.memory.used, 0)
        self.assertFalse(agent.memory.nodes)
        self.assertFalse(agent.memory.impressions)
        self.assertFalse(agent.memory.last_sleep)
        self.assertFalse(agent.visible)
        self.assertFalse(agent.plan)
        self.assertEqual((agent.goal, agent.intent, agent.last_result), ("", "", ""))

    def test_death_erases_mind_but_preserves_observer_history(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        seed_memories(sim.agent)
        sim.agent.look(sim.world)
        sim.last_prompt = sim.agent.snapshot()
        sim.event("Sekret", "UNIQUE_LOG_MARKER")
        sim.phase = "error"
        sim.agent.energy = 1
        sim.update(0)
        sim.update(5)
        self.assert_erased(sim.agent)
        self.assertEqual(sim.phase, "dead")
        self.assertFalse(sim.last_prompt)
        self.assertTrue(any(e["text"] == "UNIQUE_LOG_MARKER" for e in sim.events))
        self.assertEqual(sim.events[-1]["kind"], "death")
        self.assertNotIn("UNIQUE_", json.dumps(sim.agent.to_dict()))
        sim.retry()
        sim.request_sleep()
        sim.update(999)
        self.assertEqual(sim.phase, "dead")
        self.assertIsNone(sim.pending)

    def test_action_that_exhausts_energy_does_not_move_or_eat(self):
        for command in ({"action":"go_to","position":[8,7]}, {"action":"look","angle":45},
                        {"action":"eat","target":"meal"}, {"action":"wait","seconds":1}):
            world, agent = empty_world(), Agent("one", (7,7))
            world.add_agent(agent)
            world.add_object("food", (7.58,7), identity="meal")
            seed_memories(agent)
            agent.energy = ENERGY.action
            result = execute(agent, world, command)
            self.assertFalse(result.success)
            self.assert_erased(agent)
            self.assertEqual(agent.position, (7,7))
            self.assertIn("meal", world.objects)

    def test_food_prevents_death_only_when_creature_can_afford_to_eat(self):
        for energy, survives in ((2 * ENERGY.action, False), (2 * ENERGY.action + .01, True)):
            world, agent = empty_world(), Agent("one",(7,7))
            world.add_agent(agent)
            food = world.add_object("food",(7.58,7))
            agent.energy = energy
            result = execute(agent,world,{"action":"eat","target":food.id})
            self.assertEqual(result.success, survives)
            self.assertEqual(agent.alive, survives)
            if survives:
                self.assertAlmostEqual(agent.energy, ENERGY.food + .01)
            else:
                self.assertIn(food.id, world.objects)

    def test_death_during_consolidation_never_applies_reflection(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        seed_memories(sim.agent)
        result = ScriptedBrain().reflect(sim.agent.snapshot())
        sim.agent.energy = ENERGY.consolidation_cost(sim.agent.memory.used)
        future = Future()
        future.set_result(result)
        sim.pending, sim.pending_kind, sim.phase = future, "sleep", "sleeping"
        sim._receive(0)
        self.assert_erased(sim.agent)
        self.assertEqual(sim.phase, "dead")
        self.assertNotIn("Retrospekcja", [e["title"] for e in sim.events])
        attempt = next(e for e in sim.events if e["kind"] == "sleep_pending")
        self.assertEqual(attempt["proposed_reflection"], result)
        self.assertGreater(attempt["consolidation_cost"], 0)

    def test_unaffordable_planning_or_sleep_dies_before_any_llm_request(self):
        for kind, cost in (("plan", ENERGY.planning), ("sleep", ENERGY.sleep_start)):
            with self.subTest(kind=kind):
                brain = ScriptedBrain()
                sim = Simulation(Settings(), brain)
                self.addCleanup(sim.close)
                sim.agent.energy = cost
                with patch.object(brain, "plan") as plan, patch.object(brain, "reflect") as reflect:
                    sim._submit(kind)
                    plan.assert_not_called()
                    reflect.assert_not_called()
                self.assert_erased(sim.agent)
                self.assertEqual(sim.phase, "dead")

    def test_late_plan_and_sleep_results_cannot_resurrect_memories(self):
        for kind in ("plan", "sleep"):
            with self.subTest(kind=kind):
                entered, release = threading.Event(), threading.Event()

                class DelayedBrain(ScriptedBrain):
                    def plan(self, snapshot):
                        entered.set()
                        release.wait(timeout=2)
                        return Plan("UNIQUE_GOAL_MARKER", "UNIQUE_INTENT_MARKER", ["eat"])

                    def reflect(self, snapshot):
                        entered.set()
                        release.wait(timeout=2)
                        return super().reflect(snapshot)

                sim = Simulation(Settings(), DelayedBrain())
                self.addCleanup(sim.close)
                self.addCleanup(release.set)
                sim._submit(kind)
                future = sim.pending
                self.assertTrue(entered.wait(timeout=1))
                sim.agent.energy = 0.1
                sim.update(0)
                sim.update(1)
                self.assertEqual(sim.phase, "dead")
                release.set()
                self.assertIsNone(future.result(timeout=2))
                sim.update(2)
                self.assert_erased(sim.agent)
                self.assertFalse(sim.last_prompt)

    def test_dead_agent_cannot_observe_plan_or_recreate_memories(self):
        world, agent = empty_world(), Agent("one", (7, 7))
        agent.die()
        agent.look(world)
        agent.accept_plan(Plan("cel", "opis", ["eat"]))
        with self.assertRaises(ValueError):
            agent.memory.remember(1, "nowa pamięć")
        with self.assertRaises(ValueError):
            agent.snapshot()
        with self.assertRaises(ValueError):
            agent.start_command({"action":"eat","target":"unknown"})
        self.assert_erased(agent)
        agent.energy = 100  # even an external energy injection cannot revive this lifetime
        self.assertFalse(agent.alive)

    def test_dead_save_load_and_legacy_zero_energy_save_never_restore_memory(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        seed_memories(sim.agent)
        sim.agent.energy = 0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dead.json"
            sim.save(path)
            self.assertNotIn("UNIQUE_", path.read_text())
            loaded = Simulation.load(path, Settings(), ScriptedBrain())
            self.addCleanup(loaded.close)
            self.assertEqual(loaded.phase, "dead")
            self.assert_erased(loaded.agent)
        legacy = Agent("old", (7, 7))
        seed_memories(legacy)
        saved = legacy.to_dict()
        saved.pop("dead")
        saved["energy"] = 0
        self.assert_erased(Agent.from_dict(saved))


class BrainCancellationTests(unittest.TestCase):
    def test_late_http_response_does_not_repopulate_brain_or_trigger_repair(self):
        brain = LocalLLM(Settings(model="test"))
        entered, release = threading.Event(), threading.Event()
        errors = []

        def response(path, payload):
            entered.set()
            release.wait(timeout=2)
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"goal":"cel","intent":"opis","actions":["unknown"]}',
            }}]}

        def run():
            try:
                brain.plan({"private": "UNIQUE_MEMORY_MARKER"})
            except BrainError as exc:
                errors.append(str(exc))

        with patch.object(brain, "_request", side_effect=response) as request:
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(timeout=1))
                self.assertTrue(brain.last_snapshot)
                brain.forget()
            finally:
                release.set()
                worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(request.call_count, 1)
            self.assertTrue(errors)
            self.assertEqual(brain.last_snapshot, {})
            self.assertEqual(brain.last_metrics, {})


if __name__ == "__main__":
    unittest.main()
