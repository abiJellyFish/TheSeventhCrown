"""JSON 数据加载器 —— 生物、武器、AI 配置。"""
import pytest
from core.loader import DataLoader
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@pytest.fixture
def loader():
    return DataLoader(DATA_DIR)


class TestLoader:
    def test_load_creature(self, loader):
        g = loader.load_creature("goblin_brawler")
        assert g.name == "地精打手"
        assert g.hp > 0

    def test_load_weapons(self, loader):
        weapons = loader.load_json("items/weapons")
        assert isinstance(weapons, list)
        assert len(weapons) > 0

    def test_load_creature_behavior(self, loader):
        """测试从 creatures.json 加载生物时行为表被正确读取。"""
        g = loader.load_creature("goblin_brawler")
        assert len(g.behavior_table) > 0
        assert "hunt" in g.behavior_table
        assert g.behavior_overrides.get("hunt") == 0.8
