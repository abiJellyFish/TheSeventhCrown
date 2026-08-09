"""JSON 数据加载器测试。"""

import json
import pytest
from core.loader import DataLoader
from core.entity import Creature, Weapon, Armor, Item


@pytest.fixture
def loader():
    """创建指向 test/data/ 的加载器"""
    import os
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    return DataLoader(data_dir)


class TestLoadCreature:
    def test_load_goblin_brawler(self, loader):
        c = loader.load_creature("goblin_brawler")
        assert c is not None
        assert isinstance(c, Creature)
        assert c.name == "地精打手"
        assert c.faction == "hostile"
        assert c.max_hp == 20
        assert c.max_tenacity == 6
        assert c.speed == 1
        assert c.stats["dex"] == 12
        assert len(c.actions) >= 2

    def test_load_skeleton(self, loader):
        c = loader.load_creature("skeleton")
        assert c is not None
        assert c.name == "骷髅"
        assert c.faction == "hostile"
        assert "穿刺抗性" in c.traits or "piercing_resist" in str(c.traits)
        assert c.darkvision_range == 8


class TestLoadItem:
    def test_load_weapons(self, loader):
        weapons = loader.load_all("items/weapons")
        assert len(weapons) >= 7
        names = [w["name"] for w in weapons]
        assert "长剑" in names
        assert "短弓" in names
        assert "火把" in names

    def test_load_armors(self, loader):
        armors = loader.load_all("items/armors")
        assert len(armors) >= 5
        names = [a["name"] for a in armors]
        assert "皮甲" in names
        assert "圆盾" in names


class TestLoadSpell:
    def test_load_magic_missile(self, loader):
        spells = loader.load_all("spells")
        names = [s["name"] for s in spells]
        assert "魔法飞弹" in names
        assert "护盾术" in names
        assert "疗伤术" in names


class TestLoadAI:
    def test_load_goblin_ai(self, loader):
        ai = loader.load_json("ai/goblin_brawler")
        assert "_weights" in ai
        assert "health" in ai
        assert "_hard_filters" in ai

    def test_load_skeleton_ai(self, loader):
        ai = loader.load_json("ai/skeleton")
        assert "_weights" in ai
        assert ai["_weights"]["health"] < 0.2  # skeleton doesn't care about health
