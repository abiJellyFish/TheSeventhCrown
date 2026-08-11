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

    def test_load_ai(self, loader):
        ai = loader.load_json("ai/goblin_brawler")
        assert "_weights" in ai
