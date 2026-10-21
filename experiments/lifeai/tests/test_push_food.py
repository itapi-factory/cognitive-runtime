import math
import unittest
from lifeai.agent import Agent
from lifeai.energy import ENERGY
from lifeai.world import World, Heading, Corpse
from tests.test_world_agent import empty_world, execute


class MotorTests(unittest.TestCase):
    def setUp(self):
        self.world = empty_world()
        self.agent = Agent('one', (3.,7.))
        self.agent.energy = 40
        self.world.add_agent(self.agent)

    def test_one_eat_command_walks_turns_and_eats_selected_food(self):
        food = self.world.add_object('food', (7.4,8.1))
        other = self.world.add_object('food', (5.,6.))
        result = execute(self.agent, self.world, {'action':'eat','target':food.id})
        self.assertTrue(result.success, result.message)
        self.assertEqual(self.agent.meals, 1)
        self.assertNotIn(food.id, self.world.objects)
        self.assertIn(other.id, self.world.objects)
        self.assertEqual(self.agent.age, 1)
        self.assertLess(self.agent.energy, 68)

    def test_eat_handles_food_under_body(self):
        food = self.world.add_object('food', self.agent.position)
        self.assertTrue(execute(self.agent,self.world,{'action':'eat','target':food.id}).success)
        self.assertEqual(self.agent.meals, 1)
        self.assertGreater(math.dist(self.agent.position, food.position), .4)

    def test_remembered_food_is_reached_after_turning_out_of_view(self):
        food = self.world.add_object('food',(7.,7.))
        self.agent.look(self.world, remember=True)
        execute(self.agent,self.world,{'action':'look','angle':180})
        self.assertFalse(self.agent.visible)
        self.assertTrue(execute(self.agent,self.world,{'action':'eat','target':food.id}).success)

    def test_navigation_avoids_rocks_without_pushing_or_eating_other_food(self):
        food = self.world.add_object('food',(8.,7.))
        self.agent.look(self.world, remember=True)
        rock = self.world.add_object('rock',(5.4,7.))
        result = execute(self.agent,self.world,{'action':'eat','target':food.id})
        self.assertTrue(result.success, result.message)
        self.assertEqual(rock.position,(5.4,7.))
        self.assertEqual(self.agent.meals,1)

    def test_navigation_recovers_from_contact_with_diagonal_occluding_rock(self):
        food=self.world.add_object('food',(7.4,7.8))
        self.agent.look(self.world,remember=True)
        self.agent.facing=Heading(173.7)
        rock=self.world.add_object('rock',(5.2,7.4))
        result=execute(self.agent,self.world,{'action':'eat','target':food.id})
        self.assertTrue(result.success,result.message)
        self.assertEqual(self.agent.meals,1)
        self.assertEqual(rock.position,(5.2,7.4))

    def test_target_disappears_no_replacement_and_no_hidden_tracking(self):
        food = self.world.add_object('food',(6.,7.))
        self.agent.look(self.world,remember=True)
        self.agent.facing = Heading(180)
        self.agent.look(self.world)
        del self.world.objects[food.id]
        spare = self.world.add_object('food',(5.,6.))
        result = execute(self.agent,self.world,{'action':'eat','target':food.id})
        self.assertFalse(result.success)
        self.assertIn(spare.id,self.world.objects)
        self.assertEqual(self.agent.meals,0)
        self.assertIsNone(self.agent.known_target(food.id))

    def test_go_to_is_not_an_eat_command(self):
        food = self.world.add_object('food',(5.3,7.))
        self.assertTrue(execute(self.agent,self.world,{'action':'go_to','position':[5.3,7.]}).success)
        self.assertIn(food.id,self.world.objects)
        self.assertEqual(self.agent.meals,0)

    def test_explicit_push_moves_rock_at_arbitrary_angle_and_costs_distance(self):
        for angle in (0,31,90,187,271):
            world = empty_world(); a=Agent('one',(7.,7.),Heading(angle));world.add_agent(a)
            rock=world.add_object('rock',Heading(angle).ahead(a.position,.88))
            origin=rock.position;energy=a.energy
            result=execute(a,world,{'action':'push','target':rock.id,'distance':.6})
            self.assertTrue(result.success,result.message)
            self.assertAlmostEqual(math.dist(origin,rock.position),.6)
            self.assertAlmostEqual(energy-a.energy,ENERGY.action+12,delta=.001)

    def test_blocked_push_costs_energy_without_crushing_food_or_chain(self):
        rock=self.world.add_object('rock',(3.88,7.))
        food=self.world.add_object('food',(4.8,7.))
        before=self.agent.energy
        result=execute(self.agent,self.world,{'action':'push','target':rock.id,'distance':.6})
        self.assertFalse(result.success)
        self.assertAlmostEqual(before-self.agent.energy,12.15)
        self.assertEqual(rock.position,(3.88,7.))
        self.assertIn(food.id,self.world.objects)

    def test_push_moves_living_or_dead_body_without_its_energy_or_orientation_change(self):
        for dead in (False,True):
            world=empty_world();a=Agent('a',(3.,7.));b=Agent('b',(3.72,7.),Heading(43));world.add_agent(a);world.add_agent(b)
            if dead:
                b.die();world.leave_corpse(b)
            energy=b.energy
            result=execute(a,world,{'action':'push','target':b.id,'distance':.6})
            self.assertTrue(result.success,result.message)
            body=world.entities[b.id]
            self.assertAlmostEqual(body.position[0],4.32)
            self.assertEqual(float(body.facing),43)
            self.assertEqual(b.energy,energy)
            if dead:
                self.assertIsInstance(body,Corpse)
                self.assertFalse(b.memory.context())
            else:
                self.assertIn('To nie był mój krok',b.last_result)
                self.assertNotIn('istota a',b.memory.context())

    def test_food_exists_initially_but_never_regrows_including_load(self):
        world=World()
        self.assertTrue(any(o.kind=='food' for o in world.objects.values()))
        world.objects={k:o for k,o in world.objects.items() if o.kind!='food'}
        for _ in range(1000):world.advance()
        world=World.from_dict(world.to_dict())
        for _ in range(1000):world.advance()
        self.assertFalse(any(o.kind=='food' for o in world.objects.values()))
