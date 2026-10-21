import math
import unittest
from lifeai.agent import Agent
from lifeai.world import Direction, Heading, World


def empty_world():
    return World(15, 15, generate=False)


def execute(agent, world, command, dt=.02):
    agent.look(world, remember=True)
    agent.start_command(command)
    for _ in range(math.ceil(46 / dt)):
        result = agent.step_motor(world, dt)
        if result:
            return result
    raise AssertionError('Motor did not terminate')


class ContinuousWorldTests(unittest.TestCase):
    def setUp(self):
        self.world = empty_world()
        self.agent = Agent('one', (7.13, 7.27), vision_range=4)
        self.world.add_agent(self.agent)

    def test_senses_are_continuous_cone_range_and_occlusion(self):
        ahead = self.world.add_object('food', (10.01, 7.31))
        behind = self.world.add_object('food', (6.02, 7.31))
        far = self.world.add_object('food', (12.12, 7.31))
        side = self.world.add_object('food', (8.13, 9.27))
        ids = {o.id for o in self.world.perceive(self.agent)}
        self.assertEqual(ids, {ahead.id})
        rock = self.world.add_object('rock', (8.9, 7.29))
        self.assertEqual({o.id for o in self.world.perceive(self.agent)}, {rock.id})
        self.agent.facing = Heading(173.3)
        self.assertIn(behind.id, {o.id for o in self.world.perceive(self.agent)})

    def test_hidden_contents_do_not_enter_context_or_navigation(self):
        hidden = self.world.add_object('food', (3.1, 7.2))
        self.agent.look(self.world, remember=True)
        self.assertNotIn(hidden.id, str(self.agent.snapshot()))
        self.assertIsNone(self.agent.known_target(hidden.id))
        self.assertFalse(hasattr(self.world, 'grid'))
        self.assertFalse(hasattr(self.agent.memory, 'map'))
        result = execute(self.agent, self.world, {'action':'eat', 'target':hidden.id})
        self.assertFalse(result.success)
        self.assertEqual(self.agent.position, (7.13, 7.27))

    def test_swept_collision_prevents_tunnelling_and_bounds_escape(self):
        self.world.add_object('rock', (9.01, 7.27))
        self.assertFalse(self.world.clear_segment(self.agent.position, (12, 7.27), excluding=('one',)))
        self.assertFalse(self.world.clear_segment(self.agent.position, (-2, 7), excluding=('one',)))
        self.assertTrue(self.world.clear_segment(self.agent.position, (7.5, 10.3), excluding=('one',)))

    def test_rotation_is_smooth_arbitrary_and_in_place(self):
        self.agent.start_command({'action':'look', 'angle':73.4})
        self.assertIsNone(self.agent.step_motor(self.world, .1))
        self.assertAlmostEqual(self.agent.facing, 18)
        while self.agent.motor:
            self.agent.step_motor(self.world, .1)
        self.assertAlmostEqual(self.agent.facing, 73.4)
        self.assertEqual(self.agent.position, (7.13, 7.27))

    def test_continuous_save_roundtrip_and_legacy_conversion(self):
        self.world.add_object('food', (8.123, 9.765))
        self.assertEqual(World.from_dict(self.world.to_dict()).to_dict(), self.world.to_dict())
        saved = self.agent.to_dict()
        saved['heading'] = 123.456
        restored = Agent.from_dict(saved)
        self.assertAlmostEqual(restored.facing, 123.456)
        data = {'width':5,'height':5,'seed':1,'tick':10,'grid':[['empty']*5 for _ in range(5)]}
        data['grid'][2][3] = 'food'
        converted = World.from_dict(data)
        self.assertEqual(next(iter(converted.objects.values())).position, (3.,2.))
        self.assertNotIn('grid', converted.to_dict())

    def test_generated_objects_do_not_overlap_solids_or_spawn(self):
        for seed in range(4):
            world = World(seed=seed)
            self.assertTrue(world.clear_position((12.5,10.5)))
            for obj in world.objects.values():
                self.assertTrue(world.clear_position(obj.position, obj.radius, (obj.id,)))
