import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lifeai.agent import Agent
from lifeai.brain import BrainError, Plan, SYSTEM, SLEEP_SYSTEM, STORY_SYSTEM, parse_plan, render_context
from lifeai.config import Settings
from lifeai.simulation import Simulation
from lifeai.world import Corpse, Direction, Tile
from tests.test_simulation import ScriptedBrain
from tests.test_world_agent import empty_world, execute


class DiscoveryTests(unittest.TestCase):
    def test_snapshot_does_not_reveal_causal_rules_or_prescribe_a_survival_strategy(self):
        agent = Agent("one", (7, 7))
        body = agent.snapshot()["self"]
        self.assertEqual(body["energy"], 78)
        for secret in ("death_at_zero", "energy_costs", "next_consolidation_cost",
                       "hunger", "seconds_to_death"):
            self.assertNotIn(secret, body)
        for prompt in (SYSTEM, SLEEP_SYSTEM, STORY_SYSTEM):
            for rule in ("death_at_zero", "self.energy_costs", "below 45", "above 70",
                         "28 energy", "12 energy", "Sleep reduces fatigue",
                         "reaching zero kills", "Energy <= 0", "Unspoken experience dies"):
                self.assertNotIn(rule, prompt)

    def test_model_thought_is_bounded_memory_and_outcome_is_a_transient_measurement(self):
        world, agent = empty_world(), Agent("one", (7, 7))
        world.add_agent(agent)
        agent.accept_plan(Plan("Badam", "Użyję ust", [], thought="Przypuszczam, że przedmiot może zmieniać stan mojego ciała."))
        food = world.add_object("food", (7.58,7))
        agent.energy = 40
        execute(agent, world, {"action":"eat","target":food.id})
        self.assertIn("Przypuszczam", agent.memory.nodes[0].text)
        self.assertIn("40.00 → 67.70", agent.memory.impressions[-1].text)
        self.assertLessEqual(agent.memory.used, agent.memory.budget)
        agent.die()
        self.assertEqual(agent.memory.context(), "")

    def test_deliberately_unhelpful_plan_is_not_replaced_by_a_survival_algorithm(self):
        world, agent = empty_world(), Agent("one", (7, 7))
        food = world.add_object("food", (7.58,7))
        sim = Simulation(Settings(), ScriptedBrain(), world=world, agent=agent)
        self.addCleanup(sim.close)
        agent.energy = 3
        agent.accept_plan(Plan("Eksperyment", "Czekam", [{"action":"wait","seconds":1}]))
        sim.phase = "acting"
        sim.update(0)
        self.assertEqual(agent.meals, 0)
        self.assertIn(food.id, world.objects)
        self.assertAlmostEqual(agent.energy, 2.85 - .6)  # command startup plus concurrent analysis

    def test_body_measurements_before_and_after_thinking_enter_bounded_memory(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        sim._submit("plan")
        sim.pending.result(timeout=2)
        sim.agent.elapse(2, "thinking")
        sim._receive(0)
        notes = [e.text for e in sim.agent.memory.impressions]
        self.assertTrue(any("Przed pracą umysłu" in text and "78.00" in text for text in notes))
        self.assertTrue(any("Po pracy umysłu" in text and "76.80" in text for text in notes))

    def test_automatic_sleep_does_not_interrupt_autonomous_eating(self):
        world,agent=empty_world(),Agent('one',(7,7))
        food=world.add_object('food',(8.8,7))
        sim=Simulation(Settings(),ScriptedBrain(),world=world,agent=agent)
        self.addCleanup(sim.close)
        agent.accept_plan(Plan('Zjem','Pójdę do jedzenia',[{'action':'eat','target':food.id}]))
        agent.memory.pressure=True;sim.phase='acting';sim.action_delay=0
        sim.update(0)
        for i in range(1,100):
            sim.update(i*.05)
            if agent.meals:break
        self.assertEqual(agent.meals,1)
        if sim.pending_kind == 'plan':
            sim.pending.result(timeout=2)
            sim.update(i*.05)
        if sim.phase != 'sleeping':
            sim.update(i*.05)
        self.assertEqual(sim.phase,'sleeping')

    def test_explicit_sleep_still_precedes_the_plan(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        sim.agent.accept_plan(Plan("cel", "opis", [{"action":"go_to","position":[8,7]}]))
        sim.phase = "acting"
        sim.request_sleep()
        position = sim.agent.position
        sim.update(0)
        self.assertEqual(sim.phase, "sleeping")
        self.assertEqual(sim.agent.position, position)


class CorpseTests(unittest.TestCase):
    def setUp(self):
        self.world = empty_world()
        self.agent = Agent("one", (7, 7))
        self.sim = Simulation(Settings(), ScriptedBrain(), world=self.world, agent=self.agent)
        self.other = self.sim.add_companion(brain=ScriptedBrain())
        self.other.agent.position = (9, 7)
        self.addCleanup(self.sim.close)

    def test_corpse_is_a_separate_inert_object_with_no_mind_and_no_cause_in_senses(self):
        self.other.agent.memory.remember(0, "SECRET_LIFE_STORY", 1)
        self.other.agent.die("SECRET_CAUSE")
        self.other._handle_death()
        corpse = self.world.occupant((9, 7))
        self.assertIsInstance(corpse, Corpse)
        for field in ("memory", "brain", "energy", "death_reason", "plan"):
            self.assertFalse(hasattr(corpse, field))
        self.agent.look(self.world)
        snapshot = self.agent.snapshot()
        self.assertIn(f"agent:{corpse.id}", [c["kind"] for c in snapshot["perception"]])
        self.assertFalse(snapshot["conversation"]["partners"])
        self.assertFalse(self.world.can_address(self.agent, corpse))
        self.assertFalse(self.world.can_talk(self.agent, corpse))
        self.assertFalse(self.world.walkable(corpse.position))
        encoded = json.dumps(snapshot)
        self.assertNotIn("SECRET_", encoded)
        self.assertNotIn("death_reason", encoded)
        with patch.object(self.other.agent, "elapse") as metabolize, \
                patch.object(self.other.brain, "plan") as plan:
            self.sim.phase = "error"  # keep the living observer idle without pausing the world
            self.sim.update(500)
            metabolize.assert_not_called()
            plan.assert_not_called()

    def test_discovery_uses_eyes_and_retains_only_observed_identity_and_location(self):
        self.agent.look(self.world)
        self.assertFalse(hasattr(self.agent.memory, "map"))
        self.other.agent.die("not seen")
        self.other._handle_death()
        rock = self.world.add_object("rock", (8,7))
        self.agent.look(self.world)
        self.assertFalse(any(c.kind == f"agent:{self.other.agent.id}" for c in self.agent.visible))
        self.assertFalse(hasattr(self.agent.memory, "map"))
        del self.world.objects[rock.id]
        self.agent.look(self.world)
        self.assertTrue(any(c.kind == f"agent:{self.other.agent.id}" for c in self.agent.visible))
        self.assertEqual(self.agent.memory.nodes[-1].source, "observation")
        self.assertNotIn("not seen", self.agent.memory.context())  # no causal conclusion

    def test_recognized_identity_and_prior_testimony_survive_without_inserting_a_conclusion(self):
        story = "Jestem głodny i szukam jedzenia. Przy kamieniu nie mogłem znaleźć przejścia."
        self.agent.memory.remember_story(1, story, self.other.agent.id, self.other.agent.name)
        memory_before = self.agent.memory.to_dict()
        before = self.sim._snapshot()
        living_cell = next(c for c in before["perception"] if c.get("name") == "Bruno")
        self.assertNotIn("appearance", living_cell)

        self.other.agent.position = self.agent.mouth_position
        self.other.agent.die("HIDDEN_CAUSE")
        self.other._handle_death()
        after = self.sim._snapshot()
        still_cell = next(c for c in after["perception"] if c.get("name") == "Bruno")
        self.assertEqual(living_cell["kind"], still_cell["kind"])
        self.assertFalse(still_cell["alive"])
        self.assertIn("martwa istota", still_cell["appearance"])
        self.assertIn(story, self.agent.memory.context())
        context = render_context(after)
        self.assertIn(story, context)
        self.assertIn("cudze świadectwo: Bruno", context)
        self.assertIn("istota Bruno (id: bruno-02)", context)
        self.assertIn("martwa istota Bruno", context)
        for hidden in ("HIDDEN_CAUSE", "corpse:", "umarł z głodu"):
            self.assertNotIn(hidden, context)
        self.assertFalse(self.other.agent.memory.context())

    def test_lost_contact_does_not_reveal_an_unseen_death(self):
        self.agent.look(self.world)
        self.agent.facing = Direction.WEST
        self.agent.look(self.world)
        self.other.agent.die("HIDDEN_CAUSE")
        self.other._handle_death()
        self.agent.talk_target = self.other.agent.id
        self.sim._submit("talk")
        self.assertIsNone(self.sim.pending)
        snapshot = json.dumps(self.agent.snapshot(), ensure_ascii=False)
        self.assertNotIn("corpse:", snapshot)
        self.assertNotIn("HIDDEN_CAUSE", snapshot)
        self.assertNotIn("nieruchomo", snapshot)
        self.assertNotIn("Nie otrzymałam odpowiedzi", self.agent.last_result)
        self.assertNotIn("umarł", self.agent.last_result)
        self.assertIn("kontaktu", self.agent.last_result)

    def test_save_load_restores_corpse_as_inert_object_without_reviving_memories(self):
        self.other.agent.die()
        self.other._handle_death()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            self.sim.save(path)
            loaded = Simulation.load(path, Settings(), ScriptedBrain())
            self.addCleanup(loaded.close)
            self.assertIsInstance(loaded.world.entities[self.other.agent.id], Corpse)
            controller = loaded.controllers[self.other.agent.id]
            self.assertEqual(controller.phase, "dead")
            self.assertEqual(controller.agent.memory.context(), "")
            self.assertIsNone(controller.pending)


if __name__ == "__main__":
    unittest.main()
