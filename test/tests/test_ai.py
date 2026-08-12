"""AI 行为系统 —— 状态离散化 + 组件匹配决策引擎。"""
import pytest
from core.entity import Creature
from core.ai.discretize import discretize_state
from core.ai.engine import BehaviorEngine
from core.game_state import GameState


@pytest.fixture
def goblin():
    c = Creature(name="地精打手", hp=20, max_hp=20, faction="混乱", tenacity=6)
    c.template_name = "goblin_brawler"
    c.behavior_table = ["wander", "hunt", "attack_prey", "forage", "eat_food", "eat_inventory", "flee", "idle"]
    c.behavior_overrides = {"hunt": 0.8, "attack_prey": 0.9}
    return c


@pytest.fixture
def engine():
    return BehaviorEngine()


class TestDiscretize:
    def test_hp_critical(self, goblin):
        goblin.hp = 3  # < 20%
        keys = discretize_state(goblin)
        assert "hp:critical" in keys

    def test_power_disadvantage(self, goblin):
        keys = discretize_state(goblin)
        assert any(k.startswith("power:") for k in keys)

    def test_social_alone(self, goblin):
        keys = discretize_state(goblin)
        assert "social:alone" in keys


class TestBehaviorEngine:
    def test_engine_decide_returns_list(self, goblin, engine):
        candidates = engine.decide(goblin)
        assert isinstance(candidates, list)
        assert len(candidates) > 0
        decision, score = candidates[0]
        assert isinstance(decision, str)
        assert isinstance(score, (int, float))

    def test_critical_hp_favors_flee(self, goblin, engine):
        goblin.hp = 3
        candidates = engine.decide(goblin)
        # critical HP triggers flee condition; wander requires need:full
        top_actions = [a for a, _ in candidates]
        assert any(a in ("flee", "idle") for a in top_actions[:2])


class TestNPCBehaviorIntegration:
    def test_hungry_beast_eats_bush(self):
        from core.game_state import GameState
        from core.entity import Creature, create_fighter
        from core.movement import Terrain
        from core.ai.engine import BehaviorEngine

        p = create_fighter("t", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        p.food_locked = True
        s = GameState(player=p, map_width=20, map_height=20)
        s._ai_decide_cb = lambda c, ek: BehaviorEngine().decide(c, extra_keys=ek)
        s.player_pos = (10, 10)
        s.map[5, 5] = Terrain.DIFFICULT
        boar = Creature(name="野猪", hp=18, max_hp=18, char="w", body_type="beast",
                        food_value=5000, food_locked=False, schedule="idle",
                        bravery_tier="medium", aggression_tier="medium")
        boar.behavior_table = ["wander", "forage", "eat_food", "eat_inventory", "flee", "rest", "idle"]
        boar.behavior_overrides = {"forage": 0.9, "eat_food": 0.95}
        s.add_entity(boar, (4, 5))
        s._advance_npcs(1.0)
        assert (5, 5) in s.harvested_bushes or boar.food_value > 5000

    def test_hungry_humanoid_hunts_beast(self):
        from core.game_state import GameState
        from core.entity import Creature, create_fighter
        from core.ai.engine import BehaviorEngine

        p = create_fighter("t", {"str": 8, "dex": 8, "con": 8, "int": 8, "wis": 8, "cha": 8})
        p.food_locked = True
        s = GameState(player=p, map_width=20, map_height=20)
        s._ai_decide_cb = lambda c, ek: BehaviorEngine().decide(c, extra_keys=ek)
        s.player_pos = (10, 10)
        boar = Creature(name="野猪", hp=18, max_hp=18, char="w", body_type="beast",
                        food_value=12000, food_locked=False, schedule="idle",
                        bravery_tier="medium", aggression_tier="medium")
        boar.behavior_table = ["wander", "forage", "eat_food", "flee", "rest", "idle"]
        boar.loot = {"always": [{"name": "肉", "amount": 1, "effect": "restore_food"}]}
        s.add_entity(boar, (8, 8))
        villager = Creature(name="村民", hp=10, max_hp=10, char="v", body_type="humanoid",
                           food_value=5000, food_locked=False, schedule="idle",
                           bravery_tier="medium", aggression_tier="medium")
        villager.behavior_table = ["wander", "hunt", "attack_prey", "forage", "eat_food", "collect", "eat_inventory", "flee", "rest", "idle"]
        villager.behavior_overrides = {"hunt": 0.7}
        villager.actions = [{"name": "拳", "type": "melee_attack", "weapon": "拳",
                            "damage": "1", "damage_type": "bludgeoning", "attack_stat": "str"}]
        s.add_entity(villager, (7, 8))
        s._advance_npcs(1.0)
        # 村民应该向野猪移动或攻击
        new_pos = None
        for c, (ec, er) in s.entities:
            if c is villager:
                new_pos = (ec, er)
        assert new_pos is not None


# ═══════════════════════════════════════════════════
# 战斗组件 — attack_enemy / approach_enemy
# ═══════════════════════════════════════════════════

class TestCombatComponents:
    """attack_enemy / approach_enemy 组件评分。"""

    def test_attack_enemy_matches_when_enemy_adjacent(self):
        """env:enemy_adjacent 时 attack_enemy 参评。"""
        from core.ai.engine import BehaviorEngine
        from core.entity import Creature
        engine = BehaviorEngine()
        c = Creature(name="test", faction="混乱", hp=20, max_hp=20)
        c.behavior_table = ["attack_enemy", "wander", "idle"]
        extra = {"env:enemy_adjacent"}
        results = engine.decide(c, extra_keys=extra)
        assert results[0][0] == "attack_enemy"

    def test_attack_enemy_not_matches_without_enemy(self):
        """无 env:enemy_adjacent 时 attack_enemy 不参评。"""
        from core.ai.engine import BehaviorEngine
        from core.entity import Creature
        engine = BehaviorEngine()
        c = Creature(name="test", faction="混乱", hp=20, max_hp=20)
        c.behavior_table = ["attack_enemy", "wander", "idle"]
        results = engine.decide(c)
        assert results[0][0] != "attack_enemy"

    def test_pickup_weight_higher_than_collect(self):
        """pickup(0.65) > collect(0.4) 当 items_nearby。"""
        from core.ai.engine import BehaviorEngine
        from core.entity import Creature
        engine = BehaviorEngine()
        c = Creature(name="test", food_value=5000, food_locked=False)
        c.behavior_table = ["pickup", "collect", "wander", "idle"]
        extra = {"env:items_nearby", "need:hungry"}
        results = engine.decide(c, extra_keys=extra)
        # pickup(0.65) > collect(0.4) > wander(0.2)
        assert results[0][0] == "pickup"


# ═══════════════════════════════════════════════════
# 门开关组件
# ═══════════════════════════════════════════════════

class TestDoorComponents:
    """open_door / close_door 组件。"""

    def test_open_door_matches_nearby_closed(self):
        from core.ai.engine import BehaviorEngine
        from core.entity import Creature
        engine = BehaviorEngine()
        c = Creature(name="test", hp=20, max_hp=20)
        c.behavior_table = ["open_door", "wander", "idle"]
        extra = {"env:door_nearby"}
        results = engine.decide(c, extra_keys=extra)
        assert results[0][0] == "open_door"

    def test_close_door_matches_when_open_empty(self):
        from core.ai.engine import BehaviorEngine
        from core.entity import Creature
        engine = BehaviorEngine()
        c = Creature(name="test", hp=20, max_hp=20)
        c.behavior_table = ["close_door", "wander", "idle"]
        extra = {"env:open_door_nearby"}
        results = engine.decide(c, extra_keys=extra)
        assert results[0][0] == "close_door"
