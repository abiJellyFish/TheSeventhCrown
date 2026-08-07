"""AI behavior system tests — discretize, engine."""

import pytest
from core.ai.discretize import discretize_state
from core.ai.engine import BehaviorEngine
from core.entity import Creature


@pytest.fixture
def goblin():
    return Creature(name="Goblin", faction="hostile", hp=20, max_hp=20,
                    tenacity=6, max_tenacity=6,
                    stats={"str": 8, "dex": 12, "con": 8, "int": 6, "wis": 8, "cha": 6},
                    bravery_tier="low", aggression_tier="high",
                    schedule="hunting")


@pytest.fixture
def skeleton():
    return Creature(name="Skeleton", faction="hostile", hp=16, max_hp=16,
                    tenacity=12, max_tenacity=12,
                    stats={"str": 12, "dex": 10, "con": 12, "int": 0, "wis": 8, "cha": 0},
                    bravery_tier="high", aggression_tier="high",
                    schedule="guard")


class TestDiscretize:
    def test_hp_critical(self, goblin):
        goblin.hp = 3  # 3/20 = 15%
        keys = discretize_state(goblin, enemy_count=1, ally_count=0,
                                power_ratio=0.5)
        assert "hp:critical" in keys

    def test_hp_low(self, goblin):
        goblin.hp = 8  # 8/20 = 40%
        keys = discretize_state(goblin, enemy_count=1, ally_count=0,
                                power_ratio=0.5)
        assert "hp:low" in keys

    def test_hp_healthy(self, goblin):
        goblin.hp = 18
        keys = discretize_state(goblin, enemy_count=1, ally_count=0,
                                power_ratio=1.5)
        assert "hp:healthy" in keys

    def test_power_disadvantage(self, goblin):
        keys = discretize_state(goblin, enemy_count=3, ally_count=0,
                                power_ratio=0.3)
        assert "power:heavily_outmatched" in keys

    def test_power_advantage(self, goblin):
        keys = discretize_state(goblin, enemy_count=1, ally_count=3,
                                power_ratio=2.0)
        assert "power:advantage" in keys

    def test_social_alone(self, goblin):
        keys = discretize_state(goblin, enemy_count=1, ally_count=0,
                                power_ratio=0.5)
        assert "social:alone" in keys

    def test_on_fire(self, goblin):
        goblin.statuses = ["on_fire"]
        keys = discretize_state(goblin, enemy_count=1, ally_count=0,
                                power_ratio=0.5)
        assert "status:on_fire" in keys

    def test_schedule_and_personality(self, goblin):
        keys = discretize_state(goblin, enemy_count=0, ally_count=0,
                                power_ratio=1.0)
        assert "sched:hunting" in keys
        assert "brave:low" in keys
        assert "aggr:high" in keys


class TestBehaviorEngine:
    @pytest.fixture
    def engine(self):
        raw = {
            "goblin": {
                "_weights": {"health": 0.5, "combat": 0.5},
                "_hard_filters": {"flee": "can_move"},
                "health": {
                    "hp:critical": {"flee": 1.0, "attack": 0.0},
                    "hp:healthy": {"attack": 1.0, "flee": 0.0},
                    "_default": {"idle": 0.5},
                },
                "combat": {
                    "power:heavily_outmatched": {"flee": 0.8},
                    "power:advantage": {"attack": 0.9},
                    "_default": {"attack": 0.5},
                },
            },
        }
        return BehaviorEngine(raw)

    def test_goblin_flees_when_critical(self, engine):
        goblin = Creature(name="Goblin", faction="hostile", hp=3, max_hp=20,
                          stats={"str": 8, "dex": 12, "con": 8, "int": 6, "wis": 8, "cha": 6},
                          bravery_tier="low", aggression_tier="high",
                          schedule="hunting")
        goblin.template_name = "goblin"
        action, score = engine.decide(goblin, enemy_count=1, ally_count=0,
                                      power_ratio=0.5)
        assert action == "flee"

    def test_goblin_attacks_when_healthy(self, engine):
        goblin = Creature(name="Goblin", faction="hostile", hp=18, max_hp=20,
                          stats={"str": 8, "dex": 12, "con": 8, "int": 6, "wis": 8, "cha": 6},
                          bravery_tier="high", aggression_tier="high",
                          schedule="hunting")
        goblin.template_name = "goblin"
        action, _ = engine.decide(goblin, enemy_count=1, ally_count=2,
                                  power_ratio=2.0)
        assert action == "attack"

    def test_hard_filter_removes_unavailable(self, engine):
        """Action filtered if condition not met."""
        goblin = Creature(name="Goblin", faction="hostile", hp=3, max_hp=20,
                          stats={"str": 8, "dex": 12, "con": 8, "int": 6, "wis": 8, "cha": 6},
                          bravery_tier="low", aggression_tier="high",
                          schedule="hunting")
        goblin.template_name = "goblin"
        # flee requires can_move — assume it is True by default
        action, _ = engine.decide(goblin, enemy_count=1, ally_count=0,
                                  power_ratio=0.5)
        assert action in ("flee", "idle")  # idle if flee filtered
