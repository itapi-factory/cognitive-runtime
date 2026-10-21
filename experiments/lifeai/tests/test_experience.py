import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from lifeai.agent import Agent
from lifeai.brain import LocalLLM, Plan, render_context
from lifeai.config import Settings
from lifeai.memory import Memory
from lifeai.simulation import Simulation
from tests.test_simulation import ScriptedBrain
from tests.test_conversation import StoryBrain
from tests.test_world_agent import empty_world


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(Settings(), ScriptedBrain(), world=empty_world(), agent=Agent('ada', (3, 7)))
        self.agent = self.sim.agent
        self.addCleanup(self.sim.close)

    def begin(self, action=None, **kwargs):
        plan = Plan('Poznać własny ruch', 'Sprawdzę kierunek oczu.',
                    [action or {'action': 'look', 'angle': 90}],
                    expectation='Po obrocie spodziewam się innego widoku, ale nie innego miejsca ciała.', **kwargs)
        self.sim._apply_decision(plan)
        return self.agent.experience.rows()[-1]

    def finish(self):
        for i in range(100):
            if self.agent.motor is None:
                if not self.agent.plan:
                    return
                self.sim._start_body_command(i)
            self.sim._advance_motor(i, dt=.1)
        self.fail('Motor did not finish')

    def test_expectation_precedes_result_and_review_needs_a_link(self):
        node = self.begin()
        self.assertEqual(node.experience['state'], 'active')
        self.assertFalse(node.experience['outcomes'])
        prediction = node.experience['expectation']
        self.finish()
        self.assertEqual(node.experience['expectation'], prediction)
        self.assertEqual(node.experience['state'], 'ready')
        self.assertIn('kierunek oczu 90.0°', node.text)
        self.assertIn('Energia:', node.text)
        context = self.agent.experience.snapshot()
        unrelated = self.agent.memory.add_thought('Inna sprawa nadal mnie zastanawia i chcę do niej wrócić.', 1)
        self.agent.experience.reviewed(unrelated, context)
        self.assertEqual(node.experience['state'], 'ready')
        thought = self.agent.memory.add_thought(
            f'Obrót zmienił kierunek oczu, a miejsce mojego ciała pozostało to samo. [[{node.id}]]', 2)
        self.agent.experience.reviewed(thought, context)
        self.assertEqual(node.experience['state'], 'reviewed')
        self.assertIn(node.id, thought.links)

    def test_inflight_reflection_cannot_claim_to_have_reviewed_a_later_result(self):
        node = self.begin()
        before = self.agent.experience.snapshot()
        self.finish()
        thought = self.agent.memory.add_thought(f'Chcę poczekać na rzeczywisty wynik rozpoczętej próby. [[{node.id}]]', 2)
        self.agent.experience.reviewed(thought, before)
        self.assertEqual(node.experience['state'], 'ready')

    def test_continue_keeps_intention_and_replacement_records_interruption(self):
        node = self.begin({'action': 'go_to', 'position': [12, 7]})
        self.sim._start_body_command(0)
        self.sim._apply_decision(Plan('Inny tytuł', 'Kontynuuję.', [], control='continue'))
        self.assertEqual(self.agent.goal, 'Poznać własny ruch')
        self.assertEqual(len(self.agent.experience.rows()), 1)
        self.sim._apply_decision(Plan('Inny cel', 'Zmieniam zamiar po nowej obserwacji.',
                                     [{'action': 'look', 'angle': 90}], expectation='Zobaczę inną stronę.'))
        self.assertEqual(node.experience['state'], 'ready')
        self.assertIn('Zmieniam zamiar', node.text)
        self.assertNotIn('Dotarłam', node.text)

    def test_queued_prediction_does_not_receive_current_commands_outcome(self):
        first = self.begin({'action': 'go_to', 'position': [4, 7]})
        self.sim._start_body_command(0)
        queued = self.begin({'action': 'look', 'angle': 90}, control='queue')
        self.assertEqual(queued.experience['state'], 'queued')
        while self.agent.motor:
            self.sim._advance_motor(1, dt=.1)
        self.assertEqual(first.experience['state'], 'ready')
        self.assertFalse(queued.experience['outcomes'])
        self.finish()
        self.assertEqual(queued.experience['state'], 'ready')
        self.assertNotIn('Dotarłam', queued.text)

    def test_failed_navigation_is_a_result_without_a_fabricated_success(self):
        node = self.begin({'action': 'go_to', 'position': [-5, 7]})
        self.finish()
        self.assertEqual(node.experience['state'], 'ready')
        self.assertNotIn('Dotarłam', node.text)
        self.assertTrue(node.experience['outcomes'])

    def test_sleep_preserves_unreviewed_evidence_and_its_original_prediction(self):
        node = self.begin()
        self.finish()
        original = node.text
        self.agent.memory.consolidate(
            f'Próba obrotu dała wynik do porównania z przewidywaniem, lecz nie wyjaśnia wszystkiego. [[{node.id}]]')
        self.assertIn(node, self.agent.memory.nodes)
        self.assertEqual(node.text, original)
        self.assertIn(node.id, self.agent.memory.nodes[-1].links)
        self.assertLessEqual(self.agent.memory.used, self.agent.memory.budget)

    def test_sleep_interpretation_marks_only_the_cited_trial_reviewed(self):
        node = self.begin()
        self.finish()
        self.sim._request_memory_ids = set(self.agent.memory.valid_ids)
        self.sim._request_experiences = self.agent.experience.snapshot()
        future = Future()
        future.set_result(f'Porównuję wynik obrotu z oczekiwaniem; moja pozycja pozostała taka sama. [[{node.id}]]')
        self.sim.pending, self.sim.pending_kind, self.sim.phase = future, 'sleep', 'sleeping'
        energy = self.agent.energy
        self.sim._receive(0)
        self.assertEqual(node.experience['state'], 'reviewed')
        self.assertLess(self.agent.energy, energy)
        self.assertFalse(self.sim.error)

    def test_actual_reply_reopens_the_speech_prediction_with_attributed_evidence(self):
        other = self.sim.add_companion(brain=StoryBrain())
        other.agent.position = (5, 7)
        self.sim._apply_decision(Plan('Poznać cudzą perspektywę', 'Zapytam o zmianę widoku.',
                                     [{'action': 'talk'}], listener_id=other.agent.id,
                                     speech_intent='Zapytam o obrót.', expectation='Być może opisze podobną zmianę widoku.'))
        trial = self.agent.experience.rows()[-1]
        self.agent.experience.start()
        self.sim._deliver_story('Czy po obrocie jedzenie też było po innej stronie? Nie rozumiem jeszcze tej zmiany.')
        context = self.agent.experience.snapshot()
        thought = self.agent.memory.add_thought(f'Wypowiedziałam pytanie, ale jego sens nadal czeka na odpowiedź. [[{trial.id}]]', 1)
        self.agent.experience.reviewed(thought, context)
        self.assertEqual(trial.experience['state'], 'reviewed')
        other.agent.talk_target = self.agent.id
        other._deliver_story('Nie wiem.')
        self.assertEqual(trial.experience['state'], 'ready')
        self.assertIn('Nie wiem.', trial.text)
        self.assertEqual(trial.origins[other.agent.id], 'Bruno')

    def test_visible_corpse_does_not_repeat_notices_when_memory_is_evicted(self):
        other = self.sim.add_companion(brain=ScriptedBrain())
        other.agent.position = (5, 7)
        other.agent.die()
        other._handle_death()
        self.sim._refresh_senses()
        revision = self.agent.death_notice_revision
        self.agent.memory.nodes.clear()
        for _ in range(5):
            self.sim._refresh_senses()
        self.assertEqual(self.agent.death_notice_revision, revision)

    def test_hard_budget_can_forget_experiments_without_a_hidden_copy(self):
        self.agent.memory = Memory(600)
        for i in range(30):
            self.begin()
            self.finish()
            self.assertLessEqual(self.agent.memory.used, 600)
        self.assertGreater(self.agent.memory.forgotten, 0)
        self.assertLessEqual(len(self.agent.experience.snapshot()), len(self.agent.memory.nodes))
        self.agent.die()
        self.assertFalse(self.agent.experience.snapshot())

    def test_loading_active_trial_records_an_interruption_not_completion(self):
        node = self.begin({'action': 'go_to', 'position': [12, 7]})
        self.sim._start_body_command(0)
        self.sim._advance_motor(1, dt=.1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.json'
            self.sim.save(path)
            loaded = Simulation.load(path, Settings(), ScriptedBrain())
            self.addCleanup(loaded.close)
            restored = next(n for n in loaded.agent.memory.nodes if n.id == node.id)
            self.assertEqual(restored.experience['state'], 'ready')
            self.assertIn('Wyniku nie znam', restored.text)
            self.assertNotIn('Dotarłam', restored.text)
            self.assertFalse(loaded.agent.motor)

    def test_recognition_of_dead_bruno_recalls_his_earlier_words(self):
        bruno = self.sim.add_companion(brain=ScriptedBrain())
        bruno.agent.position = (5, 7)
        story = self.agent.memory.remember_story(0,
            'Jestem głodny i szukam jedzenia. Przy kamieniu nie znalazłem przejścia.', bruno.agent.id, 'Bruno')
        bruno.agent.die('HIDDEN_CAUSE')
        bruno._handle_death()
        snapshot = self.sim._snapshot()
        self.assertIn(story.id, snapshot['recalled_ids'])
        self.assertNotIn('HIDDEN_CAUSE', render_context(snapshot))
        self.assertFalse(any(n.source == 'insight' for n in self.agent.memory.nodes))

    def test_low_energy_affects_real_motion_but_does_not_choose_food(self):
        other = Agent('weak', (3, 7))
        other.energy = 5
        self.assertLess(other.movement_speed, self.agent.movement_speed)
        world = empty_world()
        world.add_agent(other)
        self.agent.start_command({'action': 'go_to', 'position': [8, 7]})
        other.start_command({'action': 'go_to', 'position': [8, 7]})
        self.agent.step_motor(self.sim.world, .5)
        other.step_motor(world, .5)
        self.assertLess(other.position[0], self.agent.position[0])
        self.assertEqual(other.meals, 0)
        other.sense_body(1, 'Pierwszy odczyt.')
        other.spend_energy(1, 'test')
        other.elapse(1, 'observe')
        other.sense_body(2, 'Drugi odczyt.')
        self.assertIn('Od poprzedniego odczytu', other.memory.context())
        self.assertNotIn('umrzesz', other.memory.context())

    def test_llm_must_revisit_a_completed_trial_and_supply_a_prediction(self):
        node = self.begin()
        self.finish()
        snapshot = self.sim._snapshot()
        brain = LocalLLM(Settings(model='test'))
        thought = f'Wynik obrotu zgadza się ze zmianą kierunku oczu, lecz nie wyjaśnia ruchu innych obiektów. [[{node.id}]]'
        plan = {'goal': 'Obserwować', 'intent': 'Porównam drugi obrót.',
                'actions': [{'action': 'look', 'angle': 180}]}
        corrected = dict(plan, expectation='Kierunek oczu zmieni się, ale moje miejsce powinno pozostać takie samo.')
        with patch.object(brain, '_complete', side_effect=['Bez nowego spostrzeżenia.', thought, plan, corrected]) as request:
            result = brain.plan(snapshot)
        self.assertEqual(result.expectation, corrected['expectation'])
        self.assertEqual(request.call_count, 4)
        self.assertIn('wyniku wcześniejszej próby', request.call_args_list[1].args[1]['validation_feedback'])
        self.assertIn('expectation', request.call_args_list[3].args[1]['validation_feedback'])


if __name__ == '__main__':
    unittest.main()
