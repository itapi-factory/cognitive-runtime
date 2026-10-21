import copy
import unittest
from concurrent.futures import Future
from unittest.mock import patch

from lifeai.agent import Agent
from lifeai.brain import BrainError, LocalLLM, Plan, PlanValidationError, parse_plan, render_context
from lifeai.config import Settings
from lifeai.simulation import Simulation
from tests.test_conversation import StoryBrain
from tests.test_simulation import ScriptedBrain
from tests.test_world_agent import empty_world


def talk_plan(listener='bruno-02', prefix=(), control='replace'):
    return {'goal': 'Spotkanie', 'intent': 'Chcę zapytać o ostatnią wyprawę.',
            'expectation': 'Być może usłyszę odpowiedź o wyprawie; cisza tego nie potwierdzi.',
            'control': control, 'actions': [*prefix, {'action': 'talk'}],
            'listener_id': listener, 'speech_intent': 'Co zmieniło się podczas wyprawy?'}


class ListenerPlanningTests(unittest.TestCase):
    def setUp(self):
        self.world = empty_world()
        self.ada = Agent('ada-01', (3, 7))
        self.bruno = Agent('bruno-02', (5, 7), name='Bruno')
        self.world.add_agent(self.ada)
        self.world.add_agent(self.bruno)
        self.ada.look(self.world, remember=True)
        self.bruno.position = (12, 12)
        self.ada.look(self.world)
        self.snapshot = self.ada.snapshot()
        self.brain = LocalLLM(Settings(model='test'))

    def decision(self, data, snapshot=None):
        with patch.object(self.brain, '_prose', return_value='Bez nowego spostrzeżenia.'), \
                patch.object(self.brain, '_complete', return_value=data):
            return self.brain.plan(snapshot or self.snapshot)

    def test_unavailable_listener_feedback_names_rejected_id_and_actual_availability(self):
        with self.assertRaises(PlanValidationError) as error:
            self.decision(talk_plan())
        self.assertIn('bruno-02', str(error.exception))
        self.assertIn('Aktualnie w zasięgu: nikogo', str(error.exception))
        self.assertIn('go_to', str(error.exception))
        self.assertEqual(error.exception.rejected_plan, talk_plan())

    def test_explicit_approach_then_talk_to_remembered_being_is_valid(self):
        commands = [{'action': 'go_to', 'target': self.bruno.id}]
        plan = self.decision(talk_plan(prefix=commands))
        self.assertEqual(plan.actions, commands + [{'action': 'talk'}])
        self.assertEqual(plan.listener_id, self.bruno.id)

    def test_speech_parameters_inside_talk_preserve_explicit_approach(self):
        data = talk_plan(prefix=[{'action': 'go_to', 'target': self.bruno.id}])
        for key in ('listener_id', 'speech_intent'):
            data['actions'][-1][key] = data.pop(key)
        plan = self.decision(data)
        self.assertEqual(plan.actions, [{'action': 'go_to', 'target': self.bruno.id}, {'action': 'talk'}])
        self.assertEqual(plan.listener_id, self.bruno.id)
        self.assertIn('wyprawy', plan.speech_intent)
        self.assertIn('listener_id', data['actions'][-1])  # input is not mutated

    def test_conflicting_speech_parameters_and_unknown_nested_listener_are_rejected(self):
        data = talk_plan()
        data['actions'][-1]['listener_id'] = 'other'
        with self.assertRaisesRegex(BrainError, 'Sprzeczne listener_id'):
            parse_plan(data, 5)
        data = talk_plan('invented')
        for key in ('listener_id', 'speech_intent'):
            data['actions'][-1][key] = data.pop(key)
        with self.assertRaises(PlanValidationError):
            self.decision(data)

    def test_talk_can_be_queued_after_current_approach_to_that_being(self):
        self.ada.start_command({'action': 'go_to', 'target': self.bruno.id})
        plan = self.decision(talk_plan(control='queue'), self.ada.snapshot())
        self.assertEqual(plan.control, 'queue')
        self.assertEqual(plan.actions, [{'action': 'talk'}])

    def test_approach_does_not_enable_talk_to_unknown_food_or_unrelated_target(self):
        food = self.world.add_object('food', (4, 7))
        self.ada.look(self.world, remember=True)
        snapshot = self.ada.snapshot()
        for listener, target in [('invented', 'invented'), (food.id, food.id), ('bruno-02', food.id)]:
            with self.subTest(listener=listener, target=target), self.assertRaises(PlanValidationError):
                self.decision(talk_plan(listener, [{'action': 'go_to', 'target': target}]), snapshot)

    def test_plain_talk_to_present_being_still_works_and_repair_lists_exact_ids(self):
        self.bruno.position = (5, 7)
        self.ada.look(self.world)
        snapshot = self.ada.snapshot()
        self.assertEqual(self.decision(talk_plan(), snapshot).listener_id, self.bruno.id)
        with self.assertRaises(PlanValidationError) as error:
            self.decision(talk_plan('Bruno'), snapshot)
        self.assertIn('listener_id: bruno-02', str(error.exception))

    def test_empty_current_partner_list_is_explicit_even_with_old_stories(self):
        snapshot = dict(self.snapshot, task='plan', memory='Bruno stał obok mnie i rozmawialiśmy.')
        text = render_context(snapshot)
        self.assertIn('Samo talk jest teraz niewykonalne', text)
        self.assertIn('nie wybieraj samego talk', text)
        self.assertIn('Bruno stał obok', text)

    def test_invalid_target_feedback_identifies_which_command_needs_correction(self):
        with self.assertRaises(PlanValidationError) as error:
            self.decision({'goal': 'Próba', 'intent': 'Podejdę do jedzenia.',
                           'actions': [{'action': 'eat', 'target': 'food-unknown'}]})
        self.assertIn('food-unknown', str(error.exception))
        self.assertIn('bruno-02', str(error.exception))


class PlanRecoveryTests(unittest.TestCase):
    def make_sim(self, brain=None):
        sim = Simulation(Settings(), brain or ScriptedBrain(), world=empty_world(), agent=Agent('ada-01', (3, 7)))
        self.addCleanup(sim.close)
        return sim

    def test_rejected_talk_recovers_with_fresh_context_then_executes_models_food_choice(self):
        brain = LocalLLM(Settings(model='test'))
        sim = self.make_sim(brain)
        food = sim.world.add_object('food', (4.5, 7))
        thought = 'Moje wspomnienie spotkania nie jest dowodem obecnego kontaktu.'
        snapshots = []
        replies = iter([thought, talk_plan(), talk_plan(), 'Bez nowego spostrzeżenia.',
                        {'goal': 'Sprawdzić pożywienie', 'intent': 'Podejdę do jedzenia.',
                         'expectation': 'Sprawdzę, czy po jedzeniu zmieni się odczyt mojego ciała.',
                         'actions': [{'action': 'eat', 'target': food.id}]}])
        def complete(system, snapshot, kind):
            snapshots.append(copy.deepcopy(snapshot))
            return next(replies)
        with patch.object(brain, '_complete', side_effect=complete):
            sim.update(0)
            with self.assertRaises(PlanValidationError):
                sim.pending.result(timeout=2)
            sim.update(0)
            self.assertTrue(sim.retry_is_validation)
            self.assertAlmostEqual(sim.retry_at, .1)
            self.assertIn(thought, sim.agent.memory.context())
            sim.agent.position = (3.2, 7)  # fresh retry must not reuse the old view
            sim.update(.1)
            sim.pending.result(timeout=2)
            self.assertIn('bruno-02', snapshots[-2]['validation_feedback'])
            self.assertEqual(snapshots[-2]['self']['position'], [3.2, 7])
            self.assertEqual(snapshots[-2]['conversation']['partners'], [])
            sim.update(.1)
            self.assertFalse(sim.plan_feedback)
            self.assertFalse(sim.error)
            self.assertEqual(sim.phase, 'acting')
            for i in range(2, 25):
                sim.update(i * .1)
                if sim.agent.meals:
                    break
            self.assertEqual(sim.agent.meals, 1)
            self.assertTrue(sim.agent.alive)
            self.assertTrue(any(e['kind'] == 'plan_rejected' for e in sim.events))

    def test_repeated_validation_errors_never_accumulate_network_backoff(self):
        class RejectingBrain(ScriptedBrain):
            def plan(self, snapshot):
                self.snapshot = copy.deepcopy(snapshot)
                raise PlanValidationError('Nie ma rozmówcy teraz; poprzedni plan nie został wykonany.')
        brain = RejectingBrain()
        sim = self.make_sim(brain)
        now = 0
        for _ in range(7):
            sim.update(now)
            with self.assertRaises(PlanValidationError):
                sim.pending.result(timeout=2)
            sim.update(now)
            self.assertAlmostEqual(sim.retry_at - now, .1)
            now = sim.retry_at
        self.assertIn('validation_feedback', brain.snapshot)
        self.assertEqual(sim.agent.age, 0)  # no fabricated fallback action
        self.assertFalse(sim.agent.plan)

    def test_transport_error_after_validation_starts_network_backoff_at_one_second(self):
        sim = self.make_sim()
        for exc, expected in [(PlanValidationError('Bad decision'), .1), (BrainError('offline'), 1)]:
            future = Future(); future.set_exception(exc)
            sim.pending, sim.pending_kind = future, 'plan'
            sim._receive(0)
            self.assertEqual(sim.retry_at, expected)

    def test_failed_background_plan_does_not_stop_current_motor_or_queue(self):
        sim = self.make_sim()
        sim.agent.start_command({'action': 'go_to', 'position': [12, 7]})
        sim.agent.plan.append({'action': 'look', 'angle': 90})
        motor, queue = sim.agent.motor, list(sim.agent.plan)
        future = Future(); future.set_exception(PlanValidationError('Niedostępny rozmówca.'))
        sim.pending, sim.pending_kind, sim.phase = future, 'plan', 'thinking'
        sim.update(0)
        self.assertIs(sim.agent.motor, motor)
        self.assertEqual(list(sim.agent.plan), queue)
        sim.update(.08)
        self.assertGreater(sim.agent.position[0], 3)

    def test_death_erases_persisted_correction_context(self):
        sim = self.make_sim()
        sim.plan_feedback = 'PRIVATE_REJECTED_INTENTION'
        sim.retry_is_validation = True
        sim.agent.die()
        sim._handle_death()
        self.assertFalse(sim.plan_feedback)
        self.assertFalse(sim.retry_is_validation)

    def test_contact_is_rechecked_after_explicit_approach(self):
        sim = self.make_sim(StoryBrain())
        other = sim.add_companion(brain=StoryBrain())
        other.agent.position = (7, 7)
        other.phase = 'error'  # no independent decisions in this fixture
        sim.agent.look(sim.world, remember=True)
        sim.agent.accept_plan(Plan('Spotkanie', 'Podejdę i porozmawiam.',
                                   [{'action': 'go_to', 'target': other.agent.id}, {'action': 'talk'}],
                                   listener_id=other.agent.id, speech_intent='Zapytam o podróż.'))
        sim.next_thought_lifetime = 100
        sim.action_delay = 0
        sim.update(0)
        for i in range(1, 100):
            sim._advance_motor(i * .05, dt=.05)
            if sim.agent.motor is None:
                break
        self.assertEqual(sim.agent.plan[0]['action'], 'talk')
        other.agent.position = (12, 12)
        sim._update_behavior(5)
        self.assertFalse(sim.conversations)
        self.assertFalse(any(n.source == 'testimony' for n in other.agent.memory.nodes))
        self.assertIn('kontaktu', sim.agent.last_result)
        self.assertFalse(sim.error)
        self.assertNotEqual(sim.phase, 'retrying')


if __name__ == '__main__':
    unittest.main()
