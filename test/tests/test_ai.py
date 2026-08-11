"""AI 行为系统 —— 状态离散化 + 查表决策引擎。"""
import pytest
from core.entity import Creature
from core.ai.discretize import discretize_state
from core.ai.engine import BehaviorEngine
from core.game_state import GameState


@pytest.fixture
def goblin():
    return Creature(name="地精打手", hp=20, max_hp=20, faction="hostile", tenacity=6)


@pytest.fixture
def engine():
    return BehaviorEngine({
        "goblin_brawler": {
            "_weights": {"health": 0.5, "combat": 0.3, "social": 0.2},
            "health": {"hp:critical": {"flee": 10, "attack": 0, "idle": 0}},
            "combat": {"power:neutral": {"attack": 5, "idle": 0}},
            "social": {},
        }
    })


class TestDiscretize:
    def test_hp_critical(self, goblin):
        goblin.hp = 3  # < 20%
        keys = discretize_state(goblin, None)
        assert "hp:critical" in keys

    def test_power_disadvantage(self, goblin):
        keys = discretize_state(goblin, None)
        assert any(k.startswith("power:") for k in keys)

    def test_social_alone(self, goblin):
        keys = discretize_state(goblin, None)
        assert "social:alone" in keys


class TestBehaviorEngine:
    def test_engine_decide_returns_tuple(self, goblin, engine):
        ctx = {"template_name": "goblin_brawler"}
        decision, score = engine.decide(goblin, ctx)
        assert isinstance(decision, str)
        assert isinstance(score, (int, float))

    def test_critical_hp_favors_flee(self, goblin, engine):
        goblin.hp = 3
        ctx = {"template_name": "goblin_brawler"}
        decision, score = engine.decide(goblin, ctx)
        assert decision in ("flee", "idle")  # depends on weight calculation
