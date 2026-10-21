import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from lifeai.config import Settings
from lifeai.energy import ENERGY
from lifeai.simulation import Simulation
from lifeai.world import Direction, Tile
from tests.test_simulation import ScriptedBrain


class ObserverJournalTests(unittest.TestCase):
    def test_blocked_hungry_speaker_and_both_deaths_remain_reconstructable(self):
        sim = Simulation(Settings(), ScriptedBrain())
        bruno = sim.add_companion(brain=ScriptedBrain())
        self.addCleanup(sim.close)
        sim.world.objects.clear()
        sim.agent.position, sim.agent.facing = (13, 10), Direction.EAST
        bruno.agent.position, bruno.agent.facing = (12, 10), Direction.EAST
        with tempfile.TemporaryDirectory() as directory:
            path = sim.enable_journal(Path(directory) / 'journals')
            for i in range(130):
                sim.event('Obserwator', f'OBSERVER_ONLY_{i}', 'system')
            bruno.phase = 'acting'
            bruno.agent.plan = deque([{'action':'go_to','position':[13,10]}])
            bruno._update_behavior(0)
            bruno._advance_motor(3,dt=3)
            blocked = bruno.events[-1]
            self.assertFalse(blocked['success'])
            self.assertEqual(blocked['before']['position'], [12, 10])
            story = 'Jestem głodny. Stoisz na mojej drodze i nie mogę przejść. Czy możesz się odsunąć?'
            bruno.agent.talk_target = sim.agent.id
            bruno._deliver_story(story)
            bruno.agent.energy = ENERGY.action
            bruno.agent.plan = deque([{'action':'look','angle':90}])
            bruno.phase = 'acting'
            bruno._update_behavior(4)
            self.assertFalse(bruno.agent.alive)
            sim.agent.look(sim.world)
            living_snapshot = json.dumps(sim._snapshot(), ensure_ascii=False)
            self.assertIn(story, living_snapshot)
            self.assertNotIn('OBSERVER_ONLY', living_snapshot)
            self.assertNotIn('Brak energii na działanie', living_snapshot)
            sim.agent.die()
            sim._handle_death()
            self.assertFalse(sim.agent.memory.nodes)
            self.assertFalse(bruno.agent.memory.nodes)
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            events = rows[1:]
            self.assertEqual(sum(e['kind'] == 'death' for e in events), 2)
            self.assertTrue(any(e['text'] == 'OBSERVER_ONLY_0' for e in events))
            received = next(e for e in events if e.get('direction') == 'received')
            self.assertEqual(received['text'], story)
            self.assertEqual(received['listener_id'], sim.agent.id)
            self.assertEqual(received['speaker_id'], bruno.agent.id)
            fatal_action = next(e for e in events if e.get('action') == 'look')
            self.assertEqual(fatal_action['body']['energy'], 0)
            self.assertGreater(fatal_action['before']['energy'], 0)
            checkpoint = Path(directory) / 'session.json'
            sim.save(checkpoint)
            saved_events = list(sim.journal.events)
            restored = Simulation.load(checkpoint, Settings(), ScriptedBrain())
            self.addCleanup(restored.close)
            self.assertEqual(restored.journal.events, saved_events)
            self.assertTrue(restored.journal.history_complete)
            self.assertGreater(len(restored.events), 130)
            self.assertFalse(restored.agent.memory.nodes)
            restored.save(checkpoint)
            self.assertEqual(restored.journal.events, saved_events)  # no duplicate death on load/save

    def test_resume_creates_new_archive_without_overwriting_previous_run(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            first = sim.enable_journal(folder / 'journals')
            sim.event('Pierwszy zapis', 'Zachowaj ten tekst.', 'system')
            checkpoint = folder / 'session.json'
            sim.save(checkpoint)
            original = first.read_bytes()
            loaded = Simulation.load(checkpoint, Settings(), ScriptedBrain())
            self.addCleanup(loaded.close)
            second = loaded.enable_journal(folder / 'journals')
            loaded.event('Kolejny zapis', 'Nowe zdarzenie po wznowieniu.', 'system')
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_bytes(), original)
            self.assertIn('Zachowaj ten tekst.', second.read_text())
            self.assertIn('Nowe zdarzenie po wznowieniu.', second.read_text())

    def test_legacy_history_is_marked_incomplete_without_inventing_missing_events(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        sim.agent.die()
        sim._handle_death()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.json'
            sim.save(path)
            data = json.loads(path.read_text())
            data['version'] = 3
            data.pop('observer_journal')
            data['controllers'][sim.agent.id]['events'] = [dict(sim.events[-1])]
            path.write_text(json.dumps(data))
            loaded = Simulation.load(path, Settings(), ScriptedBrain())
            self.addCleanup(loaded.close)
            self.assertFalse(loaded.journal.history_complete)
            self.assertEqual(len(loaded.events), 1)
            self.assertEqual(loaded.events[-1]['kind'], 'death')

    def test_temporary_disk_failure_keeps_history_and_retries_writing(self):
        sim = Simulation(Settings(), ScriptedBrain())
        self.addCleanup(sim.close)
        with tempfile.TemporaryDirectory() as directory:
            path = sim.enable_journal(Path(directory))
            with patch.object(Path, 'open', side_effect=OSError('disk full')):
                sim.event('Pierwszy', 'Zdarzenie podczas błędu dysku.', 'system')
            self.assertIn('disk full', sim.journal.error)
            sim.event('Drugi', 'Zdarzenie po naprawie dysku.', 'system')
            self.assertFalse(sim.journal.error)
            self.assertIn('Zdarzenie podczas błędu dysku.', path.read_text())
            self.assertIn('Zdarzenie po naprawie dysku.', path.read_text())


if __name__ == '__main__':
    unittest.main()
