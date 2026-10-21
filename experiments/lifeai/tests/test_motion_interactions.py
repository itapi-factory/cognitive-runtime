import math
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from lifeai.agent import Agent
from lifeai.brain import Plan, parse_plan, BrainError, render_context
from lifeai.config import Settings
from lifeai.memory import Memory
from lifeai.simulation import Simulation
from lifeai.world import Heading, Corpse
from tests.test_world_agent import empty_world, execute
from tests.test_simulation import ScriptedBrain


class GoalExecutionTests(unittest.TestCase):
    def test_background_thoughts_do_not_drive_each_motor_step(self):
        world=empty_world();a=Agent('a',(3.,7.));food=world.add_object('food',(8.,7.))
        class CountingBrain(ScriptedBrain):
            calls=0
            def plan(self,snapshot):
                self.calls+=1
                if snapshot['body_activity']['active']:
                    return Plan('Zjem', 'Dokończę dojście.', [], control='continue')
                return Plan('Zjem','Pójdę do jedzenia',[{'action':'eat','target':food.id}])
        brain=CountingBrain();sim=Simulation(Settings(),brain,world=world,agent=a)
        self.addCleanup(sim.close)
        sim.update(0);sim.pending.result(timeout=2);sim.update(0)
        for i in range(1,500):
            sim.update(i*.02)
            if a.meals:break
        self.assertEqual(a.meals,1)
        self.assertGreaterEqual(brain.calls,2)
        self.assertLessEqual(brain.calls,3)
        self.assertTrue(any(e['kind']=='motor_progress' for e in sim.events))

    def test_motion_and_energy_are_independent_of_render_frame_rate(self):
        states=[]
        for dt in (.01,.02,.1):
            world=empty_world();a=Agent('a',(3.,7.),Heading(123));world.add_agent(a)
            a.start_command({'action':'go_to','position':[9.,8.7]})
            for _ in range(round(2/dt)):a.step_motor(world,dt)
            states.append((a.position,float(a.facing),a.energy))
        for p,h,e in states[1:]:
            self.assertAlmostEqual(math.dist(p,states[0][0]),0,places=8)
            self.assertAlmostEqual(h,states[0][1],places=8)
            self.assertAlmostEqual(e,states[0][2],places=8)

    def test_invalid_motor_targets_numbers_and_legacy_steps_are_rejected(self):
        for command in ({'action':'forward'}, {'action':'look','angle':float('nan')},
                        {'action':'go_to','position':[1,float('inf')]}, {'action':'eat'},
                        {'action':'push','target':'r','distance':100}, {'action':'look','angle':True},
                        {'action':'eat','target':'x','position':[1,2]}):
            with self.subTest(command=command),self.assertRaises(BrainError):
                parse_plan({'goal':'cel','intent':'zamiar','actions':[command]},5)

    def test_death_mid_walk_stops_body_and_erases_motor_and_target_memory(self):
        world=empty_world();a=Agent('a',(3,7));world.add_agent(a)
        food=world.add_object('food',(8,7));a.look(world,remember=True)
        a.energy=.4
        a.start_command({'action':'eat','target':food.id})
        for _ in range(100):
            result=a.step_motor(world,.02)
            if result:break
        self.assertFalse(a.alive)
        self.assertIsNone(a.motor)
        self.assertEqual(a.memory.context(),'')
        self.assertIsInstance(world.entities[a.id],Corpse)
        self.assertGreater(a.position[0],3)
        self.assertLess(a.position[0],4)
        self.assertIn(food.id,world.objects)
        position=a.position
        self.assertIsNone(a.step_motor(world,10))
        self.assertEqual(a.position,position)

    def test_pause_freezes_active_motor_and_resume_does_not_catch_up(self):
        world=empty_world();a=Agent('a',(3.,7.));sim=Simulation(Settings(),ScriptedBrain(),world=world,agent=a)
        self.addCleanup(sim.close)
        a.start_command({'action':'go_to','position':[9,7]});sim.phase='acting'
        sim.update(0);sim.update(.1);before=(a.position,a.energy)
        sim.paused=True;sim.update(1000)
        self.assertEqual(before,(a.position,a.energy))
        sim.paused=False;sim.update(2000)
        self.assertEqual(before,(a.position,a.energy))
        sim.update(2000.1);self.assertGreater(a.position[0],before[0][0])

    def test_failed_or_interrupted_goal_returns_control_and_preserves_evidence(self):
        world=empty_world();a=Agent('a',(3,7));sim=Simulation(Settings(),ScriptedBrain(),world=world,agent=a)
        self.addCleanup(sim.close)
        a.start_command({'action':'go_to','position':[-2,7]});sim.phase='acting'
        for i in range(200):
            sim._advance_motor(i*.05,dt=.05)
            if a.motor is None:break
        self.assertIsNone(a.motor)
        self.assertEqual(sim.phase,'observe')
        self.assertIn('przejścia',a.last_result)
        a.start_command({'action':'go_to','position':[8,7]});sim.phase='acting'
        sim.request_sleep();sim._update_behavior(20)
        self.assertIsNone(a.motor)
        self.assertEqual(sim.phase,'sleeping')

    def test_push_invalidates_old_motor_and_pending_plan_without_losing_thought(self):
        world=empty_world();a=Agent('a',(3,7));sim=Simulation(Settings(),ScriptedBrain(),world=world,agent=a)
        other=sim.add_companion(brain=ScriptedBrain());other.agent.position=(3.72,7)
        self.addCleanup(sim.close)
        future=Future();thought='Chcę sprawdzić, czy inna istota widzi to samo co ja.'
        future.set_result(Plan('Cel','Zamiar',[{'action':'wait','seconds':1}],thought=thought))
        other.pending,other.pending_kind,other.phase=future,'plan','thinking'
        a.look(world);a.start_command({'action':'push','target':other.agent.id,'distance':.6});sim.phase='acting'
        sim._advance_motor(1,dt=1)
        self.assertTrue(other._replan_after_request)
        other._receive(1)
        self.assertFalse(other.agent.plan)
        self.assertIn(thought,other.agent.memory.context())
        self.assertTrue(any(e['kind']=='displacement' for e in other.events))

    def test_pushed_corpse_save_load_preserves_inert_body(self):
        world=empty_world();a=Agent('a',(3,7));sim=Simulation(Settings(),ScriptedBrain(),world=world,agent=a)
        other=sim.add_companion(brain=ScriptedBrain());other.agent.position=(3.72,7)
        self.addCleanup(sim.close);other.agent.die();other._handle_death()
        execute(a,world,{'action':'push','target':other.agent.id,'distance':.6})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'save.json';sim.save(path)
            loaded=Simulation.load(path,Settings(),ScriptedBrain());self.addCleanup(loaded.close)
            body=loaded.world.entities[other.agent.id]
            self.assertIsInstance(body,Corpse)
            self.assertAlmostEqual(body.position[0],4.32)
            self.assertFalse(loaded.controllers[body.id].agent.memory.context())

    def test_seen_food_evidence_survives_reflection_and_sleep_in_shared_budget(self):
        world=empty_world();a=Agent('a',(3,7),memory_budget=800);world.add_agent(a)
        food=world.add_object('food',(6.123,7.87));a.look(world,remember=True)
        node=next(n for n in a.memory.nodes if n.observation)
        a.memory.add_thought(f'Być może ten widok zmieni się po moim obrocie. [[{node.id}]]',1)
        a.memory.consolidate(f'Wciąż nie sprawdziłam, co pozostaje za moimi plecami. [[{node.id}]]')
        self.assertIsNotNone(a.memory.target(food.id))
        self.assertIn('6.123',a.memory.context())
        self.assertLessEqual(a.memory.used,a.memory.budget)
        self.assertEqual(Memory.from_dict(a.memory.to_dict()).target(food.id),a.memory.target(food.id))
        a.die();self.assertIsNone(a.memory.target(food.id))


class ConcurrentMemoryTests(unittest.TestCase):
    def test_late_thought_can_reference_evicted_input_without_erasing_new_impressions(self):
        memory = Memory()
        old = memory.remember(0, "Pierwsze spojrzenie.")
        context_ids = set(memory.valid_ids)
        for tick in range(12):
            memory.remember(tick, "Zmieniło się położenie mojego ciała.")
        self.assertNotIn(old.id, memory.valid_ids)
        newer = list(memory.impressions)
        memory.add_thought(f"Przy pierwszym spojrzeniu miałam inne położenie niż teraz. [[{old.id}]]",
                           12, context_ids=context_ids)
        self.assertEqual(memory.impressions, newer)
        self.assertFalse(memory.nodes[0].links)

    def test_sleep_preserves_a_displacement_that_happened_after_its_snapshot(self):
        memory = Memory()
        old = memory.remember(0, "Pierwsze spojrzenie.")
        context_ids = set(memory.valid_ids)
        new = memory.remember(1, "Moje ciało zostało popchnięte podczas snu.")
        memory.consolidate(f"Pamiętam pierwsze spojrzenie, które chcę porównać z następnym. [[{old.id}]]",
                           context_ids=context_ids)
        self.assertIn(new, memory.impressions)
        self.assertNotIn(old, memory.impressions)


if __name__ == "__main__":
    unittest.main()
