import copy
import math
import threading
import unittest
from concurrent.futures import Future

from lifeai.agent import Agent
from lifeai.brain import BrainError, Plan, parse_plan, render_context
from lifeai.config import Settings
from lifeai.energy import ENERGY
from lifeai.simulation import Simulation
from tests.test_simulation import ScriptedBrain
from tests.test_world_agent import empty_world


class AsyncActivityTests(unittest.TestCase):
    def make_sim(self, command=None, brain=None):
        sim = Simulation(Settings(), brain or ScriptedBrain(), world=empty_world(), agent=Agent('a', (3., 7.)))
        self.addCleanup(sim.close)
        if command:
            sim.agent.start_command(command)
            sim.agent.step_motor(sim.world, 0)
            sim.phase = 'acting'
        sim._last_update_at = 0
        return sim

    def pending_plan(self, sim):
        future = Future()
        sim.pending, sim.pending_kind, sim.phase = future, 'plan', 'thinking'
        sim._request_activity_revision = sim.agent.activity_revision
        sim._request_memory_ids = set(sim.agent.memory.valid_ids)
        return future

    def test_real_worker_gets_detached_activity_context_while_body_moves(self):
        entered, release = threading.Event(), threading.Event()
        class BlockingBrain(ScriptedBrain):
            calls = 0
            def plan(self, snapshot):
                self.calls += 1
                self.snapshot = copy.deepcopy(snapshot)
                entered.set()
                release.wait(5)
                return Plan('Idę', 'Kontynuuję dojście.', [], control='continue')
        brain = BlockingBrain()
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]}, brain)
        self.addCleanup(release.set)
        sim._submit('plan')
        self.assertTrue(entered.wait(2))
        motor, position = sim.agent.motor, sim.agent.position
        text = render_context(brain.snapshot)
        self.assertIn('MOJE CIAŁO JEST OBECNIE AKTYWNE', text)
        self.assertIn('go_to', str(brain.snapshot['body_activity']))
        self.assertEqual(brain.snapshot['self']['position'], list(position))
        for i in range(1, 21):
            sim.update(i * .05)
        self.assertGreater(sim.agent.position[0], position[0])
        self.assertEqual(brain.snapshot['self']['position'], list(position))
        self.assertEqual(brain.snapshot['body_activity']['travelled_metres'], 0)
        self.assertEqual(brain.calls, 1)
        self.assertEqual(sim.phase, 'thinking')
        release.set()
        sim.pending.result(timeout=2)
        sim.update(1)
        self.assertIs(sim.agent.motor, motor)
        self.assertEqual(sim.phase, 'acting')

    def test_life_thinking_and_distance_costs_are_added_once(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        self.pending_plan(sim)
        before, position = sim.agent.energy, sim.agent.position
        sim.update(1)
        distance = math.dist(position, sim.agent.position)
        self.assertGreater(distance, 1)
        self.assertAlmostEqual(before - sim.agent.energy,
                               ENERGY.per_second('thinking') + distance * ENERGY.move_per_metre)

    def test_next_accepted_command_starts_while_old_analysis_is_pending(self):
        sim = self.make_sim({'action': 'wait', 'seconds': .1})
        sim.action_delay = 0
        sim.agent.plan.append({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        sim.update(.2)
        self.assertEqual(sim.agent.motor.action, 'go_to')
        sim.update(.4)
        self.assertGreater(sim.agent.position[0], 3)
        self.assertIs(sim.pending, future)
        self.assertEqual(sim.phase, 'thinking')

    def test_continue_preserves_motor_queue_and_measured_result(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        sim.agent.plan.append({'action': 'look', 'angle': 90})
        motor, queue, outcome = sim.agent.motor, list(sim.agent.plan), sim.agent.last_result
        future = self.pending_plan(sim)
        future.set_result(Plan('Idę', 'Dokończę to, co zaczęłam.', [],
                               thought='Jeszcze nie dotarłam do celu.', control='continue'))
        sim._receive(0)
        self.assertIs(sim.agent.motor, motor)
        self.assertEqual(list(sim.agent.plan), queue)
        self.assertEqual(sim.agent.last_result, outcome)
        self.assertIn('Jeszcze nie dotarłam', sim.agent.memory.context())

    def test_queue_changes_following_commands_without_interrupting_body(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        sim.agent.plan.append({'action': 'wait', 'seconds': 1})
        motor = sim.agent.motor
        future = self.pending_plan(sim)
        commands = [{'action': 'look', 'angle': 90}]
        future.set_result(Plan('Sprawdzę widok', 'Po dojściu obrócę się.', commands, control='queue'))
        sim._receive(0)
        self.assertIs(sim.agent.motor, motor)
        self.assertEqual(list(sim.agent.plan), commands)

    def test_explicit_replace_and_stop_interrupt_body(self):
        for control in ('replace', 'stop'):
            with self.subTest(control=control):
                sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
                sim.agent.plan.append({'action': 'wait', 'seconds': 1})
                future = self.pending_plan(sim)
                actions = [{'action': 'look', 'angle': 90}] if control == 'replace' else []
                future.set_result(Plan('Zmiana', 'Wybieram inny zamiar.', actions, control=control))
                sim._receive(0)
                self.assertIsNone(sim.agent.motor)
                self.assertEqual(list(sim.agent.plan), actions)
                self.assertTrue(any(e['kind'] == 'motor_cancelled' for e in sim.events))

    def test_late_decision_never_repeats_finished_meal_and_keeps_new_evidence(self):
        sim = self.make_sim()
        food = sim.world.add_object('food', (3.58, 7))
        sim.agent.look(sim.world, remember=True)
        sim.agent.start_command({'action': 'eat', 'target': food.id})
        future = self.pending_plan(sim)
        sim.update(.2)
        self.assertEqual(sim.agent.meals, 1)
        self.assertIsNone(sim.agent.motor)
        self.assertEqual(sim.phase, 'thinking')
        meal_impressions = [i for i in sim.agent.memory.impressions if i.id not in sim._request_memory_ids]
        self.assertTrue(meal_impressions)
        future.set_result(Plan('Zjem', 'Podejdę do posiłku.', [{'action': 'eat', 'target': food.id}],
                               thought='Chcę porównać stan ciała przed próbą i po niej.'))
        sim._receive(.2)
        self.assertFalse(sim.agent.plan)
        self.assertEqual(sim.agent.meals, 1)
        self.assertTrue(all(i in sim.agent.memory.impressions for i in meal_impressions))
        self.assertIn('Chcę porównać', sim.agent.memory.context())
        event = next(e for e in reversed(sim.events) if e['kind'] == 'plan')
        self.assertFalse(event['applied'])

    def test_old_stop_cannot_cancel_next_command(self):
        sim = self.make_sim({'action': 'wait', 'seconds': .1})
        sim.action_delay = 0
        sim.agent.plan.append({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        sim.update(.2)
        motor = sim.agent.motor
        future.set_result(Plan('Stop', 'Przerwę wcześniejszą czynność.', [], control='stop'))
        sim._receive(.2)
        self.assertIs(sim.agent.motor, motor)

    def test_api_failure_and_backoff_do_not_stop_motion(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        future.set_exception(BrainError('offline'))
        sim.update(.1)
        self.assertEqual(sim.phase, 'retrying')
        position, energy = sim.agent.position, sim.agent.energy
        sim.update(.5)
        self.assertGreater(sim.agent.position[0], position[0])
        self.assertLess(sim.agent.energy, energy)
        self.assertIsNone(sim.pending)
        sim.update(1.1)
        self.assertEqual(sim.phase, 'thinking')
        sim.pending.result(timeout=2)
        self.assertTrue(sim.last_prompt['body_activity']['active'])
        self.assertGreater(sim.last_prompt['body_activity']['travelled_metres'], 1)

    def test_sleep_stops_body_and_discards_in_flight_movement_decision(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        position = sim.agent.position
        sim.request_sleep()
        sim.update(.1)
        self.assertIsNone(sim.agent.motor)
        self.assertEqual(sim.agent.position, position)
        future.set_result(Plan('Idę', 'Wrócę do chodzenia.', [{'action': 'go_to', 'position': [12, 7]}]))
        sim.update(.1)
        sim.update(.1)
        self.assertEqual(sim.phase, 'sleeping')
        self.assertFalse(sim.agent.plan)
        self.assertIsNone(sim.agent.motor)
        self.assertFalse(sim.last_prompt['body_activity']['active'])

    def test_sleep_supersedes_retry_of_failed_plan(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        future.set_exception(BrainError('offline'))
        sim.update(0)
        sim.request_sleep()
        sim.update(0)
        self.assertEqual(sim.pending_kind, 'sleep')
        self.assertIsNone(sim.agent.motor)

    def test_pause_freezes_both_lanes_even_if_worker_finishes(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        sim.update(.2)
        before = sim.agent.position, sim.agent.energy
        sim.paused = True
        future.set_result(Plan('Idę', 'Kontynuuję.', [], control='continue'))
        sim.update(1000)
        self.assertIs(sim.pending, future)
        self.assertEqual(before, (sim.agent.position, sim.agent.energy))
        sim.paused = False
        sim.update(2000)
        self.assertEqual(before, (sim.agent.position, sim.agent.energy))
        sim.update(2000.1)
        self.assertGreater(sim.agent.position[0], before[0][0])

    def test_death_discards_late_worker_result_and_body(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        future.set_running_or_notify_cancel()
        sim.agent.energy = .01
        sim.update(1)
        future.set_result(Plan('Idę', 'Nowy plan.', [{'action': 'wait', 'seconds': 1}], thought='Nie wrócę.'))
        sim.update(2)
        self.assertEqual(sim.phase, 'dead')
        self.assertIsNone(sim.pending)
        self.assertIsNone(sim.agent.motor)
        self.assertFalse(sim.agent.memory.context())
        self.assertFalse(sim.agent.plan)

    def test_analysis_interval_prevents_inference_per_frame(self):
        sim = self.make_sim({'action': 'go_to', 'position': [12, 7]})
        future = self.pending_plan(sim)
        future.set_result(Plan('Idę', 'Kontynuuję.', [], control='continue'))
        sim._receive(0)
        for i in range(1, 60):
            sim.update(i * .05)
            self.assertIsNone(sim.pending)
        sim.update(3.01)
        self.assertEqual(sim.pending_kind, 'plan')
        self.assertIsNotNone(sim.agent.motor)

    def test_new_view_does_not_rewrite_evidence_of_pending_reflection(self):
        sim = self.make_sim()
        other = Agent('b', (5, 7), name='Bruno')
        sim.world.add_agent(other)
        sim.agent.look(sim.world, remember=True)
        old = next(n for n in sim.agent.memory.nodes if n.observation)
        old_text = old.text
        ids = set(sim.agent.memory.valid_ids)
        other.position = (5.5, 7)
        sim.agent.look(sim.world, remember=True)
        sim.agent.memory.add_thought(f'Pamiętam wcześniejsze miejsce spotkania. [[{old.id}]]', 1, context_ids=ids)
        self.assertEqual(old.text, old_text)
        self.assertIsNone(old.observation)
        self.assertEqual(sim.agent.memory.target(other.id)['x'], 5.5)
        self.assertIn(old.id, sim.agent.memory.nodes[-1].links)


class AsyncContractTests(unittest.TestCase):
    def test_active_body_requires_explicit_control_and_matching_actions(self):
        base = {'goal': 'Poznać', 'intent': 'Obserwuję', 'actions': []}
        for control in ('continue', 'stop'):
            self.assertEqual(parse_plan(dict(base, control=control), 5, body_active=True).control, control)
        for data, active in ((base, True), (dict(base, control='queue'), False),
                             (dict(base, control='replace'), True),
                             (dict(base, control='continue', actions=[{'action': 'wait', 'seconds': 1}]), True)):
            with self.subTest(data=data), self.assertRaises(BrainError):
                parse_plan(data, 5, body_active=active)

    def test_interval_must_be_finite_and_bounded(self):
        for interval in (0, -1, float('nan'), float('inf'), 61):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                Settings(thinking_interval=interval)


if __name__ == '__main__':
    unittest.main()
