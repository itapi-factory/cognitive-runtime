import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from lifeai.agent import Agent
from lifeai.brain import BrainError, LocalLLM, Plan, parse_plan, render_context
from lifeai.config import Settings
from lifeai.conversation import REPLY_WINDOW, RepeatedSpeech, is_repetition, validate_story
from lifeai.simulation import Simulation
from lifeai.world import Heading
from tests.test_conversation import StoryBrain
from tests.test_world_agent import empty_world


QUESTION = 'Czy po twoim obrocie jedzenie też było po innej stronie? Zastanawiam się, czy zmieniło miejsce.'
ANSWER = 'U mnie zmieniła się strona widoku, ale zapamiętane miejsce jedzenia pozostało takie samo.'


class DialogueTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(Settings(), StoryBrain(), world=empty_world(), agent=Agent('ada-01', (3, 7)))
        self.other = self.sim.add_companion(brain=StoryBrain())
        self.other.agent.position = (5, 7)
        self.other.agent.facing = Heading(180)
        self.sim.agent.talk_target = self.other.agent.id
        self.other.agent.talk_target = self.sim.agent.id
        self.addCleanup(self.sim.close)

    def ask(self):
        self.sim._deliver_story(QUESTION)
        return self.other.agent.dialogue.incoming(self.sim.agent.id)

    def test_question_and_response_have_correlated_turns_and_exact_prompt(self):
        question = self.ask()
        self.assertEqual(question.utterance['state'], 'new')
        self.assertIsNotNone(self.sim.agent.dialogue.waiting(self.other.agent.id))
        with patch.object(self.other.brain, 'narrate', return_value=ANSWER) as narrate:
            self.other._submit('talk')
            self.other.pending.result(timeout=2)
            snapshot = self.other.last_prompt
            self.assertEqual(snapshot['reply_to']['text'], QUESTION)
            self.assertIn('TERAZ ODPOWIADAM NA TE KONKRETNE SŁOWA', render_context(snapshot))
            self.assertEqual(narrate.call_count, 1)
            self.other._receive(0)
        sent = next(e for e in reversed(self.other.events) if e.get('direction') == 'sent')
        self.assertEqual(sent['in_reply_to'], question.utterance['id'])
        self.assertEqual(question.utterance['state'], 'answered')
        original = next(n for n in self.sim.agent.dialogue.rows() if n.text == QUESTION)
        self.assertEqual(original.utterance['state'], 'answered')
        self.assertIsNone(self.sim.agent.dialogue.waiting(self.other.agent.id))
        self.assertEqual(self.sim.agent.dialogue.incoming().text, ANSWER)

    def test_no_repeat_while_waiting_and_no_forced_body_wait(self):
        self.ask()
        before = self.other.agent.energy
        with patch.object(self.sim.brain, 'narrate') as narrate:
            self.sim._submit('talk')
            narrate.assert_not_called()
        for _ in range(4):
            self.sim._deliver_story(QUESTION)
        self.assertEqual(self.sim.conversations, 1)
        self.assertEqual(self.other.agent.energy, before)
        self.sim.agent.start_command({'action': 'go_to', 'position': [3, 10]})
        self.sim._advance_motor(1, dt=1)
        self.assertGreater(self.sim.agent.position[1], 7)

    def test_received_words_interrupt_old_decision_but_keep_motor_and_thought(self):
        other = self.other
        other.agent.start_command({'action': 'go_to', 'position': [5, 9]})
        motor = other.agent.motor
        other._request_memory_ids = set(other.agent.memory.valid_ids)
        future = Future()
        other.pending, other.pending_kind, other.phase = future, 'plan', 'thinking'
        thought = 'Moje położenie zmienia się podczas ruchu i chcę sprawdzić kolejne spojrzenie.'
        self.ask()
        future.set_result(Plan('Zmienię cel', 'Obrócę się.', [{'action': 'look', 'angle': 90}], thought=thought))
        other._receive(0)
        self.assertIs(other.agent.motor, motor)
        self.assertFalse(other.agent.plan)
        self.assertIn(thought, other.agent.memory.context())
        self.assertIn(QUESTION, other.agent.memory.context())
        self.assertEqual(other.next_thought_lifetime, other.agent.lifetime_seconds)
        event = next(e for e in reversed(other.events) if e['kind'] == 'plan')
        self.assertFalse(event['applied'])
        self.assertIn('wypowiedź', event['decision_note'])

    def test_receiver_may_consider_question_and_continue_moving(self):
        question = self.ask()
        other = self.other
        other.agent.start_command({'action': 'go_to', 'position': [5, 9]})
        motor = other.agent.motor
        other._submit('plan')
        other.pending.result(timeout=2)
        other._receive(0)  # test brain chooses continue
        self.assertEqual(question.utterance['state'], 'considered')
        self.assertIs(other.agent.motor, motor)
        self.assertFalse(any(a['action'] == 'talk' for a in other.agent.plan))
        self.assertGreater(other.next_thought_lifetime, other.agent.lifetime_seconds)

    def test_new_message_starts_analysis_before_the_normal_interval(self):
        self.other.next_thought_lifetime = 100
        self.other.agent.start_command({'action': 'go_to', 'position': [5, 9]})
        self.ask()
        self.other._update_behavior(0)
        self.assertEqual(self.other.pending_kind, 'plan')
        self.other.pending.result(timeout=2)
        self.assertIn(QUESTION, render_context(self.other.last_prompt))
        self.assertIsNotNone(self.other.agent.motor)

    def test_listener_can_answer_from_hearing_without_facing_speaker(self):
        self.other.agent.facing = Heading(0)
        self.assertFalse(self.sim.world.can_address(self.other.agent, self.sim.agent))
        self.ask()
        snapshot = self.other._snapshot()
        self.assertIn(self.sim.agent.id, [p['id'] for p in snapshot['conversation']['partners']])
        self.assertFalse(any(c['id'] == self.sim.agent.id for c in snapshot['perception']))
        with patch.object(self.other.brain, 'narrate', return_value='Nie wiem.'):
            self.other._submit('talk')
            self.other.pending.result(timeout=2)
            self.other._receive(0)
        self.assertEqual(self.other.conversations, 1)
        self.assertEqual(self.sim.agent.dialogue.incoming().text, 'Nie wiem.')
        self.assertEqual(float(self.other.agent.facing), 0)

    def test_recent_contact_does_not_allow_speech_through_rock_or_at_distance(self):
        self.ask()
        rock = self.sim.world.add_object('rock', (4, 7))
        self.assertIsNone(self.other._speech_target(self.sim.agent.id))
        del self.sim.world.objects[rock.id]
        self.sim.agent.position = (10, 12)
        self.assertIsNone(self.other._speech_target(self.sim.agent.id))

    def test_unseen_unknown_being_is_not_discovered_through_dialogue(self):
        self.other.agent.facing = Heading(0)
        snapshot = self.other._snapshot()
        self.assertNotIn(self.sim.agent.id, [p['id'] for p in snapshot['conversation']['partners']])

    def test_simultaneous_intentions_take_turns_without_cancelling_workers(self):
        with patch.object(self.sim.brain, 'narrate', return_value=QUESTION), \
                patch.object(self.other.brain, 'narrate', return_value=ANSWER):
            self.sim._submit('talk')
            first = self.sim.pending
            self.other.agent.plan.append({'action': 'talk'})
            self.other.next_thought_lifetime = 100  # isolate speech scheduling
            self.other._update_behavior(0)
            self.assertIsNone(self.other.pending)
            self.assertEqual(list(self.other.agent.plan), [{'action': 'talk'}])
            self.assertIs(self.sim.pending, first)
            first.result(timeout=2)
            self.sim._receive(0)
            self.other._update_behavior(1)
            self.other.pending.result(timeout=2)
            self.assertEqual(self.other.last_prompt['reply_to']['text'], QUESTION)
            self.other._receive(1)
        self.assertEqual((self.sim.conversations, self.other.conversations), (1, 1))

    def test_outdated_narration_is_not_passed_off_as_answer_to_new_question(self):
        with patch.object(self.other.brain, 'narrate', return_value=ANSWER):
            self.other._submit('talk')
            self.other.pending.result(timeout=2)
            self.ask()  # words not present in the narration snapshot
            self.other._receive(0)
        self.assertEqual(self.other.conversations, 0)
        self.assertIsNotNone(self.other.agent.dialogue.incoming())
        self.assertEqual(self.other.phase, 'observe')
        self.assertIn('nową kwestię', self.other.agent.last_result)

    def test_waiting_for_the_floor_allows_independent_thinking(self):
        with patch.object(self.sim.brain, 'narrate', return_value=QUESTION):
            self.sim._submit('talk')
            self.other.agent.plan.append({'action': 'talk'})
            self.other.next_thought_lifetime = 0
            self.other._update_behavior(0)
            self.assertEqual(self.other.pending_kind, 'plan')
            self.other.pending.result(timeout=2)
            self.assertEqual(self.sim.pending_kind, 'talk')

    def test_wait_times_out_without_diagnosing_listener_or_repeating(self):
        self.ask()
        self.sim.agent.lifetime_seconds = REPLY_WINDOW + 1
        changed = self.sim.agent.dialogue.expire(lambda peer: True)
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].utterance['state'], 'unanswered')
        self.sim._deliver_story(QUESTION)
        self.assertEqual(self.sim.conversations, 1)
        self.assertFalse(self.sim.error)
        self.assertNotEqual(self.sim.phase, 'retrying')

    def test_visible_death_closes_wait_and_preserves_testimony(self):
        question = self.ask()
        self.other._deliver_story(ANSWER)
        self.sim.agent.start_command({'action': 'wait', 'seconds': 10})
        self.sim.agent.plan.append({'action': 'talk'})
        self.other.agent.die('HIDDEN_CAUSE')
        self.other._handle_death()
        self.sim._refresh_senses()
        dialogue = self.sim.agent.dialogue.snapshot()
        self.assertFalse(dialogue['incoming'])
        self.assertFalse(dialogue['awaiting_reply'])
        self.assertIn(ANSWER, self.sim.agent.memory.context())
        self.assertNotIn('HIDDEN_CAUSE', self.sim.agent.memory.context())
        self.assertIsNone(self.sim.agent.motor)
        self.assertFalse(self.sim.agent.plan)
        self.assertEqual(self.sim.next_thought_lifetime, self.sim.agent.lifetime_seconds)

    def test_seen_death_invalidates_old_plan_without_stopping_walking(self):
        self.sim.agent.start_command({'action': 'go_to', 'position': [3, 10]})
        motor = self.sim.agent.motor
        future = Future()
        self.sim.pending, self.sim.pending_kind = future, 'plan'
        self.other.agent.die()
        self.other._handle_death()
        future.set_result(Plan('Rozmowa', 'Poczekam.', [{'action': 'wait', 'seconds': 10}]))
        self.sim._receive(0)
        self.assertIs(self.sim.agent.motor, motor)
        self.assertFalse(self.sim.agent.plan)
        self.assertFalse(next(e for e in reversed(self.sim.events) if e['kind'] == 'plan')['applied'])

    def test_dead_target_cannot_bypass_validation_by_planning_an_approach(self):
        self.other.agent.die()
        self.other._handle_death()
        snapshot = self.sim._snapshot()
        target = next(c for c in snapshot['perception'] if c['id'] == self.other.agent.id)
        plan = Plan('Rozmowa', 'Podejdę.', [{'action': 'go_to', 'target': target['id']},
                                          {'action': 'talk'}], listener_id=target['id'])
        with self.assertRaisesRegex(BrainError, 'martwa istota'):
            LocalLLM._validate_listener(plan, snapshot, {target['id']: target})

    def test_unseen_death_only_breaks_contact(self):
        self.ask()
        self.sim.agent.facing = Heading(180)
        self.other.agent.die('HIDDEN_CAUSE')
        self.other._handle_death()
        self.sim._refresh_senses()
        self.sim.agent.dialogue.expire(lambda peer: False)
        self.assertNotIn('martwa', self.sim.agent.memory.context())
        self.assertEqual(self.sim.agent.dialogue.rows()[-1].utterance['state'], 'lost_contact')

    def test_slow_analysis_does_not_erase_the_question_before_reply(self):
        question = self.ask()
        self.other.agent.dialogue.reviewed({question.id})
        self.other.agent.lifetime_seconds = REPLY_WINDOW + 10
        self.other.agent.facing = Heading(0)
        self.other.agent.dialogue.expire(lambda peer: True)
        with patch.object(self.other.brain, 'narrate', return_value='Nie wiem.'):
            self.other._submit('talk')
            self.other.pending.result(timeout=2)
            self.assertEqual(self.other.last_prompt['reply_to']['text'], QUESTION)
            self.other._receive(0)
        self.assertEqual(self.other.conversations, 1)

    def test_sleep_preserves_pending_question_without_unbounded_duplicate_transcript(self):
        question = self.ask()
        memory = self.other.agent.memory
        memory.consolidate(f'Chcę sprawdzić pytanie o różnicę między obrotem i ruchem jedzenia. [[{question.id}]]')
        self.assertEqual(self.other.agent.dialogue.incoming().text, QUESTION)
        self.assertLessEqual(memory.used, memory.budget)
        memory.budget = 600
        for i in range(80):
            memory.remember_story(i, ANSWER, 'third', 'Celina')
        self.assertLessEqual(memory.used, 600)
        self.assertIsNone(self.other.agent.dialogue.incoming())
        self.assertFalse(self.other.agent.dialogue.snapshot()['turns'])

    def test_dialogue_survives_save_load_and_dies_with_its_owner(self):
        self.ask()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            self.sim.save(path)
            loaded = Simulation.load(path, Settings(), StoryBrain())
            self.addCleanup(loaded.close)
            receiver = loaded.controllers[self.other.agent.id]
            self.assertEqual(receiver.agent.dialogue.incoming().text, QUESTION)
            self.assertIsNotNone(loaded.agent.dialogue.waiting(receiver.agent.id))
            receiver.agent.die()
            receiver._handle_death()
            self.assertFalse(receiver.agent.dialogue.snapshot()['turns'])
            self.assertTrue(any(e.get('direction') == 'received' for e in receiver.events))

    def test_reply_to_speaker_who_died_during_preparation_has_no_receiver_mind(self):
        self.ask()
        with patch.object(self.other.brain, 'narrate', return_value='Nie wiem.'):
            self.other._submit('talk')
            self.other.pending.result(timeout=2)
            self.sim.agent.die()
            self.sim._handle_death()
            self.other._receive(0)
        self.assertFalse(self.sim.agent.memory.context())
        self.assertEqual(self.other.conversations, 0)
        self.assertIn('martwa istota', self.other.agent.last_result)
        self.assertIsNone(self.other.agent.dialogue.incoming())
        self.assertFalse(self.other.error)


class DialogueContractTests(unittest.TestCase):
    def test_explicit_speech_shorthand_is_normalized_but_continue_never_speaks(self):
        data = {'goal': 'Odpowiedź', 'intent': 'Odpowiem na pytanie.', 'control': 'replace',
                'actions': [], 'listener_id': 'bruno-02', 'speech_intent': 'Porównam dwa spojrzenia.'}
        self.assertEqual(parse_plan(data, 5).actions, [{'action': 'talk'}])
        self.assertEqual(parse_plan(dict(data, control='continue'), 5).actions, [])
        data['speech_intent'] = ''
        with self.assertRaises(BrainError):
            parse_plan(data, 5)

    def test_same_short_answer_is_allowed_for_another_incoming_question(self):
        brain = LocalLLM(Settings(model='test'))
        snapshot = {'reply_to': {'text': QUESTION},
                    'dialogue': {'turns': [{'direction': 'sent', 'text': 'Nie wiem.'}]}}
        with patch.object(brain, '_complete', return_value='Nie wiem.'):
            self.assertEqual(brain.narrate(snapshot), 'Nie wiem.')

    def test_short_reply_is_valid_but_a_dump_still_is_not(self):
        self.assertEqual(validate_story('Nie wiem.', reply=True), 'Nie wiem.')
        with self.assertRaises(ValueError):
            validate_story('Nie wiem.')
        with self.assertRaises(ValueError):
            validate_story('{"memory": "test"}', reply=True)

    def test_repetition_detection_is_conservative(self):
        self.assertTrue(is_repetition(QUESTION, QUESTION))
        self.assertTrue(is_repetition(QUESTION.replace('Zastanawiam się', 'Myślę'), QUESTION))
        self.assertFalse(is_repetition(ANSWER, QUESTION))
        self.assertFalse(is_repetition('Tak.', 'Nie.'))

    def test_llm_repairs_repeated_question_using_the_actual_incoming_words(self):
        brain = LocalLLM(Settings(model='test'))
        snapshot = {'reply_to': {'text': QUESTION},
                    'dialogue': {'turns': [{'direction': 'sent', 'text': QUESTION}]}}
        with patch.object(brain, '_complete', side_effect=[QUESTION, ANSWER]) as complete:
            self.assertEqual(brain.narrate(snapshot), ANSWER)
            self.assertIn('powtórzenie', complete.call_args.args[1]['validation_feedback'])
        with patch.object(brain, '_complete', return_value=QUESTION), self.assertRaises(RepeatedSpeech):
            brain.narrate(snapshot)


if __name__ == '__main__':
    unittest.main()
