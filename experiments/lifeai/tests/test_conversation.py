import json
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from lifeai.brain import BrainError, LocalLLM, Plan, parse_plan
from lifeai.config import Settings
from lifeai.conversation import validate_story
from lifeai.energy import ENERGY
from lifeai.memory import Memory
from lifeai.simulation import Simulation, run_headless
from lifeai.world import Direction, Tile
from tests.test_simulation import ScriptedBrain

STORY = ("Wędrowałam na wschód, gdzie znalazłam pożywienie i odzyskałam siły. "
         "Skały zmusiły mnie do zawrócenia. Nauczyłam się sprawdzać drogę przed każdym krokiem.")


class StoryBrain(ScriptedBrain):
    def narrate(self, snapshot):
        self.speech_snapshot = json.loads(json.dumps(snapshot))
        return STORY


class StoryContractTests(unittest.TestCase):
    def test_narrator_repairs_script_that_plays_the_listeners_role(self):
        brain = LocalLLM(Settings(model='test'))
        snapshot = {'self': {'name': 'Bruno'}, 'listener': {'name': 'Ada'}}
        with patch.object(brain, '_complete', side_effect=['Ada: ' + STORY, STORY]) as complete:
            self.assertEqual(brain.narrate(snapshot), STORY)
            self.assertIn('Bruno', complete.call_args.args[1]['validation_feedback'])

    def test_natural_story_is_accepted_but_dumps_are_rejected(self):
        self.assertEqual(validate_story(STORY), STORY)
        invalid = [
            {"episodes": [STORY]}, '{"episodes": ["' + STORY + '"]}',
            "Pamiętam następujący zapis. memory: episodes, knowledge, map i wszystkie inne dane.",
            "- Poszłam na wschód i znalazłam jedzenie.\n- Następnie zobaczyłam skałę oraz ścianę.",
            "Pamiętam mapę: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 i wszystko tam widziałam.",
            "Zapis mojego życia to " + "A" * 80 + " i proszę zachowaj go dla przyszłych istot.",
            "Żyłam na arenie. " * 80, "Żyję.",
        ]
        for value in invalid:
            with self.subTest(value=str(value)[:60]), self.assertRaises(ValueError):
                validate_story(value)

    def test_talk_requires_recipient_and_ends_the_plan(self):
        plan = parse_plan({"goal": "Opowiedzieć", "intent": "Rozmowa",
                           "actions": [{"action":"talk"}], "listener_id": "bruno-02", "speech_intent":"Porozmawiajmy o drodze"}, 5)
        self.assertEqual(plan.listener_id, "bruno-02")
        for actions, target in ((["talk"], ""), (["talk", "eat"], "bruno-02"),
                                (["talk", "talk"], "bruno-02")):
            with self.subTest(actions=actions), self.assertRaises(BrainError):
                parse_plan({"goal": "a", "intent": "b", "actions": actions, "listener_id": target}, 5)

    def test_llm_must_rephrase_invalid_dump_and_cannot_choose_unknown_listener(self):
        brain = LocalLLM(Settings(model="test"))
        with patch.object(brain, "_complete", side_effect=[
            '{"memory": "' + STORY + '"}', STORY,
        ]) as complete:
            self.assertEqual(brain.narrate({}), STORY)
            self.assertIn("validation_feedback", complete.call_args.args[1])
        with patch.object(brain, "_prose", return_value="Bez nowego spostrzeżenia."), patch.object(brain, "_complete", return_value={
            "goal": "a", "intent": "b", "actions": [{"action":"talk"}], "listener_id": "invisible", "speech_intent":"Pytanie",
        }), self.assertRaises(BrainError):
            brain.plan({"conversation": {"partners": []}})


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(Settings(), StoryBrain())
        self.listener = self.sim.add_companion(brain=StoryBrain())
        self.addCleanup(self.sim.close)
        self.sim.world.objects.clear()
        self.sim.agent.position = (12, 10)
        self.listener.agent.position = (14, 10)
        self.sim.agent.facing = Direction.EAST
        self.listener.agent.facing = Direction.WEST
        self.sim.agent.look(self.sim.world)
        self.listener.agent.look(self.sim.world)
        self.sim.agent.talk_target = self.listener.agent.id

    def heard_stories(self):
        return [e for e in self.listener.agent.memory.nodes if e.source == "testimony"]

    def test_only_story_crosses_boundary_and_both_parties_pay(self):
        self.sim.agent.memory.remember(1, "PRIVATE_EPISODE_NOT_TOLD", 1)
        self.sim.agent.memory.add_thought("PRIVATE_SUMMARY_NOT_TOLD zawiera osobistą lekcję.", 1)
        before_nodes = list(self.listener.agent.memory.nodes)
        speaker_energy, listener_energy = self.sim.agent.energy, self.listener.agent.energy
        self.sim._deliver_story(STORY)
        episode = self.heard_stories()[0]
        self.assertEqual(episode.text, STORY)
        self.assertEqual(episode.origins, {self.sim.agent.id: self.sim.agent.name})
        self.assertEqual(self.listener.agent.memory.nodes[:-1], before_nodes)
        self.assertAlmostEqual(self.sim.agent.energy, speaker_energy - ENERGY.speech_cost(STORY))
        self.assertAlmostEqual(self.listener.agent.energy, listener_energy - ENERGY.listening_cost(STORY))
        encoded = json.dumps(self.listener.agent.snapshot(), ensure_ascii=False)
        self.assertNotIn("PRIVATE_", encoded)
        self.assertFalse(hasattr(self.listener.agent.memory, "map"))
        self.assertIsNot(self.sim.agent.memory.nodes, self.listener.agent.memory.nodes)
        spoken = self.sim.agent.memory.nodes[-1]
        self.assertEqual(spoken.audience, {self.listener.agent.id: self.listener.agent.name})
        self.assertFalse(spoken.origins)
        thought = self.sim.agent.memory.add_thought(
            f'Chcę zapamiętać komu przekazałam swoje doświadczenie. [[{spoken.id}]]', 3)
        self.assertFalse(thought.origins)
        self.assertEqual(thought.audience, spoken.audience)

    def test_story_survives_narrator_death_but_not_listener_death(self):
        self.sim._deliver_story(STORY)
        self.sim.agent.die()
        self.sim._handle_death()
        self.assertEqual(self.sim.agent.memory.context(), "")
        self.assertEqual(self.heard_stories()[0].text, STORY)
        self.assertEqual(self.listener.agent.memory.nodes[-1].origins[self.sim.agent.id], "Ada")
        self.listener.agent.die()
        self.listener._handle_death()
        self.assertEqual(self.listener.agent.memory.context(), "")

    def test_chat_delivery_ignores_distance_orientation_obstacles_and_sleep(self):
        for scenario in ("distant", "behind", "rock", "sleeping"):
            with self.subTest(scenario=scenario):
                self.sim.agent.memory = Memory()
                self.listener.agent.memory = Memory()
                self.listener.agent.position = (14, 10)
                self.sim.world.objects.clear()
                self.listener.phase = "observe"
                if scenario == "distant":
                    self.listener.agent.position = (23, 19)
                elif scenario == "behind":
                    self.listener.agent.position = (11, 10)
                elif scenario == "rock":
                    self.sim.world.add_object("rock", (13,10))
                elif scenario == "sleeping":
                    self.listener.phase = "sleeping"
                position, facing = self.sim.agent.position, self.sim.agent.facing
                before = self.sim.conversations
                self.sim._deliver_story(STORY)
                self.assertEqual(self.heard_stories()[0].text, STORY)
                self.assertEqual(self.sim.conversations, before + 1)
                self.assertEqual(self.sim.agent.position, position)
                self.assertEqual(self.sim.agent.facing, facing)
                if scenario == 'sleeping':
                    self.assertEqual(self.listener.phase, 'sleeping')

    def test_remote_chat_cannot_deliver_to_missing_or_dead_participant(self):
        self.listener.agent.position = (23, 19)
        removed = self.sim.world.entities.pop(self.listener.agent.id)
        self.sim._deliver_story(STORY)
        self.assertFalse(self.heard_stories())
        self.sim.world.entities[self.listener.agent.id] = removed
        self.listener.agent.die('HIDDEN_CAUSE')
        self.listener._handle_death()
        self.sim._deliver_story(STORY)
        self.assertFalse(self.heard_stories())
        self.assertEqual(self.sim.conversations, 0)
        self.assertIn('niedostępny na czacie', self.sim.agent.last_result)
        self.assertNotIn('martwa', self.sim.agent.memory.context())

    def test_speaker_must_survive_delivery_and_listener_must_afford_listening(self):
        self.sim.agent.energy = ENERGY.speech_cost(STORY)
        self.sim._deliver_story(STORY)
        self.assertFalse(self.sim.agent.alive)
        self.assertFalse(self.heard_stories())

    def test_unaffordable_listening_kills_recipient_without_receiving_memory(self):
        self.listener.agent.energy = ENERGY.listening_cost(STORY)
        self.sim._deliver_story(STORY)
        self.assertFalse(self.listener.agent.alive)
        self.assertEqual(self.listener.agent.memory.context(), "")
        self.assertTrue(self.sim.agent.alive)
        self.assertEqual(self.sim.conversations, 0)

    def test_narration_receives_own_context_but_no_listener_memories(self):
        self.listener.agent.memory.remember(2, "LISTENER_SECRET", 1)
        self.sim._submit("talk")
        self.sim.pending.result(timeout=2)
        payload = self.sim.brain.speech_snapshot
        self.assertEqual(payload["listener"]["id"], self.listener.agent.id)
        self.assertNotIn("LISTENER_SECRET", json.dumps(payload))
        self.sim._receive(0)
        self.assertEqual(self.heard_stories()[0].text, STORY)

    def test_recognized_dead_bruno_is_not_a_listener_and_his_story_survives(self):
        hungry = "Jestem głodny i nie mogę przejść. Czy możesz odsunąć się z mojej drogi?"
        remembered = self.sim.agent.memory.remember_story(
            0, hungry, self.listener.agent.id, self.listener.agent.name)
        self.listener.agent.die("HIDDEN_CAUSE")
        self.listener._handle_death()
        events_before = list(self.listener.events)
        energy = self.sim.agent.energy
        with patch.object(self.sim.brain, "narrate") as narrate:
            self.sim._submit("talk")
            self.assertIsNone(self.sim.pending)
            narrate.assert_not_called()
        self.assertAlmostEqual(self.sim.agent.energy, energy - ENERGY.action)
        self.assertEqual(self.sim.conversations, 0)
        self.assertEqual(self.sim.phase, "observe")
        self.assertEqual(list(self.listener.events), events_before)
        self.assertFalse(self.listener.agent.memory.context())
        self.assertIn("martwa istota", self.sim.agent.last_result)
        self.assertEqual(remembered.text, hungry)
        self.assertNotIn("HIDDEN_CAUSE", self.sim.agent.memory.context())
        self.assertFalse(any(n.source == "spoken" for n in self.sim.agent.memory.nodes))
        self.assertFalse(self.sim.agent.plan)

    def test_death_during_narration_is_observed_without_reviving_recipient(self):
        self.sim._submit("talk")
        self.sim.pending.result(timeout=2)
        self.listener.agent.die("HIDDEN_CAUSE")
        self.listener._handle_death()
        self.sim._receive(0)
        self.assertIn("martwa istota", self.sim.agent.last_result)
        self.assertNotIn("HIDDEN_CAUSE", self.sim.agent.memory.context())
        self.assertEqual(self.sim.conversations, 0)
        self.assertFalse(self.listener.agent.memory.context())
        self.assertEqual(self.listener.phase, "dead")
        self.assertIsNone(self.listener.pending)

    def test_speaker_can_die_paying_for_speech_to_living_listener(self):
        self.sim.agent.energy = ENERGY.speech_cost(STORY)
        self.sim._deliver_story(STORY)
        self.assertEqual(self.sim.phase, "dead")
        self.assertFalse(self.sim.agent.memory.context())
        self.assertTrue(self.listener.agent.alive)
        self.assertFalse(self.heard_stories())
        self.assertEqual(self.sim.conversations, 0)

    def test_listener_can_move_while_speaker_prepares_speech_even_if_narration_fails(self):
        gate = threading.Event()
        class SlowBrokenStory(StoryBrain):
            def narrate(self, snapshot):
                gate.wait(timeout=2)
                raise BrainError('Przerwane połączenie')
        self.sim.brain = SlowBrokenStory()
        self.listener.agent.plan.extend([{'action':'go_to','position':[13,10]}])
        self.listener.phase = 'acting'
        position = self.listener.agent.position
        self.sim._submit('talk')
        try:
            self.sim.update(0)
            self.sim.update(0.5)
            self.assertLess(self.listener.agent.position[0], position[0])
            self.assertLess(self.listener.agent.energy, 78)
            gate.set()
            with self.assertRaises(BrainError):
                self.sim.pending.result(timeout=2)
            self.sim._receive(0.5)
            self.assertEqual(self.sim.phase, 'retrying')
        finally:
            gate.set()

    def test_late_narration_after_death_is_discarded(self):
        entered, release = threading.Event(), threading.Event()

        class SlowStory(StoryBrain):
            def narrate(self, snapshot):
                entered.set()
                release.wait(timeout=2)
                return STORY

        self.sim.brain = SlowStory()
        self.sim._submit("talk")
        future = self.sim.pending
        self.assertTrue(entered.wait(timeout=1))
        self.sim.agent.die()
        self.sim._handle_death()
        release.set()
        self.assertIsNone(future.result(timeout=2))
        self.assertFalse(self.heard_stories())

    def test_received_story_preserves_reflection_but_requests_fresh_decision(self):
        future = Future()
        thought = "Moje ruchy mogą ułatwiać innym dostęp do jedzenia. Chcę to sprawdzić."
        future.set_result(Plan("Ustąpię", "Przesunę się", [{"action":"go_to","position":[13,10]}], thought=thought))
        self.listener.pending, self.listener.pending_kind = future, "plan"
        self.listener.phase = "thinking"
        self.sim._deliver_story(STORY)
        self.assertFalse(self.listener._replan_after_request)
        self.listener._receive(0)
        self.assertEqual(list(self.listener.agent.plan), [])
        self.assertEqual(self.listener.phase, "observe")
        self.assertIn(thought, self.listener.agent.memory.context())
        self.assertTrue(self.heard_stories())

    def test_repeated_requests_do_not_cancel_recipients_step_or_replace_last_body_result(self):
        self.listener.agent.plan.extend([{"action":"go_to","position":[13,10]}])
        self.listener.phase = "acting"
        previous_result = self.listener.agent.last_result
        for _ in range(15):
            self.sim._deliver_story(STORY)
        self.assertEqual(self.listener.agent.last_result, previous_result)
        self.listener._update_behavior(0)
        self.listener._advance_motor(2, dt=2)
        self.assertAlmostEqual(self.listener.agent.position[0],13,delta=.025)
        self.assertEqual(self.listener.agent.age, 1)
        self.assertEqual(len(self.heard_stories()), 1)

    def test_simultaneous_speech_does_not_interrupt_other_speakers_pending_request(self):
        self.listener.agent.talk_target = self.sim.agent.id
        for controller in (self.sim, self.listener):
            controller.pending = Future()
            controller.pending.set_result(STORY)
            controller.pending_kind, controller.phase = "talk", "talking"
        self.sim._receive(0)
        self.assertEqual(self.listener.phase, "talking")
        self.listener._receive(0)
        self.assertEqual(self.sim.conversations, 1)
        self.assertEqual(self.listener.conversations, 1)

    def test_all_metabolism_runs_before_delivering_any_story(self):
        future = Future()
        future.set_result(STORY)
        self.sim.pending, self.sim.pending_kind, self.sim.phase = future, "talk", "talking"
        self.sim._last_update_at = self.listener._last_update_at = 0
        self.listener.agent.energy = 0.1
        self.sim.update(1)
        self.assertFalse(self.listener.agent.alive)
        self.assertEqual(self.sim.conversations, 0)

    def test_living_companion_continues_after_primary_dies_and_pause_is_global(self):
        self.sim.agent.die()
        self.sim.update(0)
        self.listener.pending.result(timeout=2)
        self.sim.update(0)
        self.assertEqual(self.listener.phase, "acting")
        self.sim.update(1)
        self.sim.update(2)
        self.assertGreater(self.listener.agent.age, 0)
        before = self.listener.agent.energy
        self.sim.paused = True
        self.sim.update(100)
        self.assertEqual(self.listener.agent.energy, before)

    def test_save_load_preserves_testimony_when_narrator_is_dead(self):
        self.sim._deliver_story(STORY)
        self.sim.agent.die()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            self.sim.save(path)
            loaded = Simulation.load(path, Settings(), StoryBrain())
            self.addCleanup(loaded.close)
            self.assertEqual(len(loaded.controllers), 2)
            self.assertFalse(loaded.agent.alive)
            survivor = loaded.controllers[self.listener.agent.id].agent
            self.assertTrue(survivor.alive)
            self.assertEqual([e.text for e in survivor.memory.nodes if e.source == "testimony"], [STORY])
            self.assertEqual(loaded.agent.memory.context(), "")


class TestimonyMemoryTests(unittest.TestCase):
    def test_heard_story_keeps_provenance_through_repeated_sleep(self):
        memory = Memory()
        node = memory.remember_story(1, STORY, "ada-01", "Ada")
        text = f"Ada mówiła, że na wschodzie znalazła jedzenie. To cudza obserwacja, której sama nie sprawdziłam. [[{node.id}]]"
        memory.consolidate(text)
        memory.consolidate(text)
        self.assertEqual(memory.nodes[0].source, "testimony")
        self.assertEqual(memory.nodes[0].origins, {"ada-01": "Ada"})
        self.assertEqual(Memory.from_dict(memory.to_dict()).context(), memory.context())

    def test_stories_share_the_same_hard_budget_as_personal_memory(self):
        memory = Memory(600)
        for tick in range(30):
            memory.remember_story(tick, STORY, "ada-01", "Ada")
            self.assertLessEqual(memory.used, 600)
        self.assertGreater(memory.forgotten, 0)


if __name__ == "__main__":
    unittest.main()
