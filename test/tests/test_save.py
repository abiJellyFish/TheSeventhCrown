"""存档系统验收测试 —— SaveManager save/load 完整流程。"""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock


class TestSaveManager:
    """SaveManager 单元测试。"""

    @pytest.fixture
    def tmp_dir(self):
        with tempfile.TemporaryDirectory() as d:
            yield d

    @pytest.fixture
    def manager(self, tmp_dir):
        from core.save.database import SaveManager
        return SaveManager(save_dir=tmp_dir)

    @pytest.fixture
    def mock_state(self):
        state = MagicMock()
        state.current_map = "世界"
        state.player_pos = (10, 20)
        state.player.name = "凯恩"
        state.player.hp = 30
        state.player.mp = 5
        state.player.tenacity = 10
        state.player.char_class = "fighter"
        state.player.max_hp = 35
        state.player.max_mp = 5
        state.player.max_tenacity = 10
        state.player.ap = 6
        state.player.max_ap = 6
        state.player.speed = 1
        state.player.stats = {"str": 10, "dex": 8, "con": 10, "int": 8, "wis": 8, "cha": 8}
        state.player.gp = 3
        state.player.sp = 0
        state.player.cp = 0
        state.player.food_value = 15000
        state.player.food_locked = False
        state.player.vision_range = 8
        state.player.darkvision_range = 0
        state.player.statuses = []
        state.player.equipment = {}
        state.player.inventory = []
        state.player.memorized_spells = []
        state.player.faction = "friendly"
        state.entities = []
        state.clock.pendulum_count = 0
        state.clock.pendulum_acc_ticks = 0
        state.in_combat = False
        state.in_dungeon = False
        state.dungeon_entrance = None
        state.dungeon_exit = None
        state.door_states = {}
        state.bed_positions = set()
        state.world_state = None
        return state

    def test_save_creates_file(self, manager, mock_state):
        """保存应创建 JSON 文件。"""
        manager.save(mock_state, slot="test_save")
        path = os.path.join(manager._dir, "test_save.json")
        assert os.path.exists(path)

    def test_save_content_correct(self, manager, mock_state):
        """保存内容应与 state 一致。"""
        manager.save(mock_state, slot="test_save")
        path = os.path.join(manager._dir, "test_save.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["current_map"] == "世界"
        assert data["player_pos"] == [10, 20]
        assert data["player"]["name"] == "凯恩"
        assert data["player"]["hp"] == 30
        assert data["in_combat"] is False
        assert "clock" in data

    def test_load_restores_state(self, manager, mock_state):
        """读档应恢复状态字段。"""
        manager.save(mock_state, slot="test_save")
        # 修改 state
        mock_state.player.hp = 10
        mock_state.player_pos = (0, 0)
        mock_state.current_map = "???"
        # 读档
        result = manager.load(mock_state, slot="test_save")
        assert result is True
        assert mock_state.current_map == "世界"
        assert mock_state.player_pos == (10, 20)
        assert mock_state.player.hp == 30

    def test_load_nonexistent_returns_false(self, manager, mock_state):
        """读不存在的存档返回 False。"""
        result = manager.load(mock_state, slot="nonexistent")
        assert result is False

    def test_save_overwrites_existing(self, manager, mock_state):
        """同槽位再次保存应覆盖旧存档。"""
        manager.save(mock_state, slot="test_save")
        mock_state.current_map = "地下城"
        manager.save(mock_state, slot="test_save")
        path = os.path.join(manager._dir, "test_save.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["current_map"] == "地下城"

    def test_save_slot_default(self, manager, mock_state):
        """默认槽位为 quicksave。"""
        manager.save(mock_state)
        path = os.path.join(manager._dir, "quicksave.json")
        assert os.path.exists(path)

    def test_load_invalid_json_raises(self, manager, mock_state):
        """损坏的 JSON 文件应抛出异常。"""
        path = os.path.join(manager._dir, "corrupt.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not valid json{{{")
        with pytest.raises(json.JSONDecodeError):
            manager.load(mock_state, slot="corrupt")

    def test_save_dir_created(self, tmp_dir):
        """不存在的存档目录应自动创建。"""
        from core.save.database import SaveManager
        d = os.path.join(tmp_dir, "nonexistent_subdir")
        SaveManager(save_dir=d)
        assert os.path.isdir(d)
