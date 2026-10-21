import unittest
from unittest.mock import patch

from lifeai.agent import Agent
from lifeai.brain import BrainError, LocalLLM, parse_plan, render_context
from lifeai.config import Settings
from lifeai.memory import Memory, read_note, read_reflection
from tests.test_world_agent import empty_world


class MemoryTests(unittest.TestCase):
    def test_default_budget_keeps_more_than_old_limit_without_forcing_sleep(self):
        memory = Memory()
        while memory.used < 3500:
            memory.add_thought('Pamiętam spotkanie przy kamieniu i pytanie, na które nie znalazłam odpowiedzi. '
                               'Chcę porównać je z następnym spotkaniem, zanim wyciągnę ogólny wniosek.', 1)
        self.assertEqual(memory.budget, 8000)
        self.assertEqual(memory.forgotten, 0)
        self.assertFalse(memory.needs_sleep)

    def test_vision_and_repetitive_telemetry_do_not_fill_durable_memory(self):
        agent, world = Agent('one', (7, 7)), empty_world()
        for i in range(300):
            agent.look(world)
            agent.memory.remember(i, 'Obróciłam się i zauważyłam inną część otoczenia.', 0.3)
        self.assertFalse(agent.memory.nodes)
        self.assertLessEqual(len(agent.memory.impressions), 8)
        self.assertLess(agent.memory.ratio, 0.30)
        self.assertFalse(agent.needs_sleep)
        self.assertFalse(hasattr(agent.memory, 'map'))

    def test_contextual_links_are_selected_by_model_and_share_budget(self):
        memory = Memory(800)
        first = memory.add_thought('Po jedzeniu poczułam zmianę, ale nie wiem jeszcze czy dotyczy każdego przedmiotu.', 1)
        second = memory.add_thought(f'Wróciłam do wcześniejszej próby [[{first.id}]]: teraz odczyt się nie zmienił. Może byłam już nasycona?', 2)
        self.assertEqual(second.links, [first.id])
        self.assertGreater(first.strength, 1)
        self.assertNotIn('"text":', memory.context())
        for i in range(50):
            memory.add_thought('Zauważyłam związek między spotkaniem a własnym pytaniem. ' * 3, i)
            self.assertLessEqual(memory.used, memory.budget)
        ids = {n.id for n in memory.nodes}
        self.assertTrue(all(set(n.links) <= ids for n in memory.nodes))

    def test_sleep_merges_referenced_threads_without_deleting_important_uncited_nodes(self):
        memory = Memory()
        a = memory.add_thought('Pierwsza próba skończyła się inaczej, niż oczekiwałam.', 1)
        b = memory.add_thought(f'Druga próba przypomina pierwszą [[{a.id}]], lecz miała inny wynik.', 2)
        important = memory.add_thought('Bruno jest dla mnie ważny; obiecałam wrócić do jego pytania o zwłoki.', 3)
        memory.consolidate(f'Obie próby wskazują na różnicę zależną od stanu mojego ciała. Nie znam jeszcze jej granic. [[{a.id}]] [[{b.id}]]')
        self.assertEqual(len(memory.nodes), 2)
        self.assertIn(important, memory.nodes)
        self.assertLess(important.strength, 1)
        self.assertEqual(memory.last_sleep['merged'], 1)
        self.assertEqual(memory.last_sleep['forgotten'], 0)
        self.assertEqual(Memory.from_dict(memory.to_dict()).context(), memory.context())

    def test_sleep_preserves_attribution_when_merging_other_peoples_words(self):
        memory = Memory()
        n = memory.remember_story(1, 'Widziałam kamień za zakrętem i nie mogłam przejść. Zastanawiam się, czy jest inna droga.', 'bruno', 'Bruno')
        memory.add_thought(f'Bruno [[{n.id}]] szuka drogi; jego problem przypomina mój, choć go nie widziałam.', 2)
        memory.consolidate(f'Z opowieści Bruna wynika trudność przy kamieniu. Mogę pomóc mu sprawdzić inne przejście. [[{n.id}]]')
        self.assertTrue(all(n.origins.get('bruno') == 'Bruno' for n in memory.nodes))

    def test_sleep_preserves_connections_between_separately_revisited_threads(self):
        memory = Memory()
        a = memory.add_thought('Pierwsze spotkanie pozostawiło pytanie o kierunek drogi.', 1)
        b = memory.add_thought(f'Moja wyprawa wiązała się z tym pytaniem [[{a.id}]].', 2)
        memory.consolidate(
            f'Wciąż pamiętam rozmówcę i jego pytanie o drogę. [[{a.id}]]\n\n'
            f'Wyprawa dała mi odpowiedź, którą chcę przekazać rozmówcy. [[{b.id}]]')
        self.assertEqual(next(n for n in memory.nodes if n.id == b.id).links, [a.id])

    def test_invalid_links_and_json_reflections_are_rejected(self):
        with self.assertRaises(ValueError):
            read_note('Wyciągam wniosek z nieistniejącego przeżycia [[999]].', {1})
        with self.assertRaises(ValueError):
            read_reflection('{"summary":"Gotowa ogólna wiedza"}', {1})
        with self.assertRaises(ValueError):
            read_reflection('Wniosek bez odwołania do jakiegokolwiek doświadczenia.', {1})
        with self.assertRaises(ValueError):
            read_note('1. Idę dwa pola do przodu.\n2. Obracam się w prawo i szukam kolejnego przedmiotu.', set())

    def test_legacy_migration_keeps_knowledge_and_authors_without_importing_map(self):
        data = {'budget': 8000, 'context': {'summary': 'Poznałam zmianę energii po jedzeniu.',
                'knowledge': [{'text': 'Ada mówiła o przejściu za skałą.', 'speaker_ids': ['ada']}],
                'episodes': [], 'map': [[i, 1, 'empty', 1] for i in range(100)]}}
        memory = Memory.from_dict(data)
        self.assertEqual(len(memory.nodes), 2)
        self.assertTrue(memory.nodes[1].origins)
        self.assertFalse(hasattr(memory, 'map'))

    def test_death_removes_all_nodes_links_and_impressions(self):
        memory = Memory()
        memory.add_thought('Ta myśl dotyczy mojego pierwszego spotkania.', 1)
        memory.remember(2, 'Zatrzymałam się.')
        memory.erase()
        self.assertEqual(memory.context(), '')
        self.assertEqual(memory.used, 0)
        self.assertFalse(memory.nodes)
        self.assertFalse(memory.impressions)
        with self.assertRaises(ValueError):
            memory.add_thought('Nie można przywrócić tej dawnej perspektywy.', 3)


class ContractTests(unittest.TestCase):
    def test_plan_contract_rejects_unknown_empty_or_long_actions(self):
        for actions in ([], ['teleport'], ['forward'] * 6, [None], ['sleep', 'forward']):
            with self.subTest(actions=actions), self.assertRaises(BrainError):
                parse_plan({'goal': 'cel', 'intent': 'opis', 'actions': actions}, 5)

    def test_only_activity_plan_uses_json_mode_and_context_is_prose(self):
        brain = LocalLLM(Settings(model='test'))
        snapshot = Agent('one', (7, 7)).snapshot()
        responses = ['Zauważyłam, że nie znam jeszcze otoczenia; chcę porównać dwa widoki.',
                     '{"goal":"Poznać","intent":"Obrócę się","expectation":"Po obrocie spodziewam się innego widoku.","actions":[{"action":"look","angle":45}]}']
        def response(path, payload):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': responses.pop(0)}}]}
        with patch.object(brain, '_request', side_effect=response) as request:
            plan = brain.plan(snapshot)
        thought_call, plan_call = [call.args[1] for call in request.call_args_list]
        self.assertNotIn('response_format', thought_call)
        self.assertEqual(plan_call['response_format'], {'type': 'json_object'})
        self.assertEqual(plan.actions, [{'action':'look','angle':45}])
        self.assertIn('Zauważyłam', plan.thought)
        for payload in (thought_call, plan_call):
            self.assertEqual(len(payload['messages']), 2)
            self.assertFalse(payload['messages'][1]['content'].startswith('{'))
            self.assertNotIn('"memory":', payload['messages'][1]['content'])

    def test_invalid_plan_is_repaired_without_regenerating_the_successful_thought(self):
        brain = LocalLLM(Settings(model='test'))
        with patch.object(brain, '_complete', side_effect=[
            'Bez nowego spostrzeżenia.',
            {'goal': 'cel', 'intent': 'opis', 'actions': ['teleport']},
            {'goal': 'cel', 'intent': 'opis', 'actions': [{'action':'look','angle':45}]},
        ]) as complete:
            self.assertEqual(brain.plan({}).actions, [{'action':'look','angle':45}])
            self.assertEqual(complete.call_count, 3)
            self.assertIn('validation_feedback', complete.call_args.args[1])

    def test_model_discovery_uses_served_id(self):
        brain = LocalLLM(Settings())
        with patch.object(brain, '_request', return_value={'data': [{'id': 'openai/gpt-oss-20b', 'root': 'openai/gpt-oss-120b'}]}):
            self.assertEqual(brain.discover(), 'openai/gpt-oss-20b')

    def test_truncated_thought_is_not_committed(self):
        brain = LocalLLM(Settings(model='test'))
        with patch.object(brain, '_request', return_value={'choices': [{'finish_reason': 'length', 'message': {'content': 'unfinished'}}]}), self.assertRaises(BrainError):
            brain.plan({})


if __name__ == '__main__':
    unittest.main()
