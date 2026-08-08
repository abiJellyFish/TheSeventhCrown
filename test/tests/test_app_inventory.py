"""app.py 物品栏/装备函数测试 —— 防止 NameError 等回归。"""

import pytest
from unittest.mock import MagicMock

from core.entity import Player, Weapon, Item


# ═══════════════════════════════════════════════════
# _add_to_inventory 单元测试
# ═══════════════════════════════════════════════════

class TestAddToInventory:
    """模块级 _add_to_inventory 函数。"""

    @pytest.fixture
    def player(self):
        return Player.create_fighter(name="测试", stats={"str": 8, "dex": 8, "con": 8,
                                                          "int": 8, "wis": 8, "cha": 8})

    def test_add_new_item(self, player):
        from render.textual.app import _add_to_inventory
        item = Item(name="治疗药水", item_type="consumable", count=1, weight=0.5)
        _add_to_inventory(player, item)
        assert len(player.inventory) == 1
        assert player.inventory[0].name == "治疗药水"

    def test_stack_same_item(self, player):
        from render.textual.app import _add_to_inventory
        item1 = Item(name="治疗药水", item_type="consumable", count=1, weight=0.5)
        item2 = Item(name="治疗药水", item_type="consumable", count=2, weight=0.5)
        _add_to_inventory(player, item1)
        _add_to_inventory(player, item2)
        assert len(player.inventory) == 1
        assert player.inventory[0].count == 3
        # weight 叠加：0.5 + 0.5 = 1.0（weight 不带 count）

    def test_different_name_no_stack(self, player):
        from render.textual.app import _add_to_inventory
        item1 = Item(name="治疗药水", item_type="consumable", count=1, weight=0.5)
        item2 = Item(name="浆果", item_type="consumable", count=1, weight=0.1)
        _add_to_inventory(player, item1)
        _add_to_inventory(player, item2)
        assert len(player.inventory) == 2

    def test_different_type_no_stack(self, player):
        from render.textual.app import _add_to_inventory
        item1 = Item(name="短弓", item_type="weapon", count=1, weight=1.0)
        item2 = Item(name="短弓", item_type="consumable", count=1, weight=1.0)
        _add_to_inventory(player, item1)
        _add_to_inventory(player, item2)
        assert len(player.inventory) == 2


# ═══════════════════════════════════════════════════
# _equip_weapon_from_inventory / _use_item 单元测试
# ═══════════════════════════════════════════════════

class TestEquipWeapon:
    """武器从物品栏装备到手上。"""

    @pytest.fixture
    def state(self):
        """返回模拟的 game_state，player 为真实 Player 对象。"""
        s = MagicMock()
        s.in_combat = False
        s.player = Player.create_fighter(name="测试", stats={"str": 8, "dex": 8, "con": 8,
                                                              "int": 8, "wis": 8, "cha": 8})
        # 初始化空物品栏和装备栏
        s.player.inventory = []
        for slot in s.player.equipment:
            s.player.equipment[slot] = None
        return s

    @pytest.fixture
    def app(self, state):
        from unittest.mock import patch
        from render.textual.app import MVPApp
        with patch.object(MVPApp, '__init__', lambda self: None):
            app = MVPApp.__new__(MVPApp)
        app._state = state
        app._act_log = MagicMock()
        app._right_panel = MagicMock()
        app._map_view = MagicMock()
        app._input_bar = MagicMock()
        return app

    @pytest.fixture
    def player(self):
        return Player.create_fighter(name="测试", stats={"str": 8, "dex": 8, "con": 8,
                                                          "int": 8, "wis": 8, "cha": 8})

    @pytest.fixture
    def longsword(self):
        return Weapon(name="长剑", weapon_type="melee", damage="1d8",
                      damage_type="slashing", attack_stat="str", ap_cost=3)

    @pytest.fixture
    def shortbow(self):
        return Weapon(name="短弓", weapon_type="ranged", damage="1d6",
                      damage_type="piercing", attack_stat="dex",
                      ap_cost=2, range_normal=8, range_max=14,
                      properties=["ammo", "two_handed"])

    def test_equip_to_empty_hand(self, app, state, shortbow):
        """空手状态下装备武器。"""
        p = state.player
        p.inventory = [shortbow]
        p.equipment["right_hand"] = None

        app._equip_weapon_from_inventory(shortbow, 0)
        assert p.equipment["right_hand"] is shortbow
        assert len(p.inventory) == 0

    def test_equip_swaps_with_existing_weapon(self, app, state, shortbow, longsword):
        """手上已有武器时，装备新武器将旧武器放回物品栏。"""
        p = state.player
        p.inventory = [shortbow]
        p.equipment["right_hand"] = longsword

        app._equip_weapon_from_inventory(shortbow, 0)
        assert p.equipment["right_hand"] is shortbow
        assert len(p.inventory) == 1
        assert p.inventory[0] is longsword

    def test_use_item_weapon_triggers_equip(self, app, state, shortbow):
        """_use_item 识别 Weapon 类型并调用装备逻辑。"""
        p = state.player
        p.inventory = [shortbow]
        p.equipment["right_hand"] = None
        p.ap = 6

        app._use_item("I1")
        assert p.equipment["right_hand"] is shortbow
        assert len(p.inventory) == 0

    def test_use_item_consumable_consumes(self, app, state):
        """_use_item 对非武器物品走消耗逻辑。"""
        p = state.player
        potion = Item(name="治疗药水", item_type="consumable", count=1,
                      weight=0.5, effect="heal", amount="6d4", ap_cost=1)
        p.inventory = [potion]
        p.ap = 6
        p.hp = 20
        p.max_hp = 30

        app._use_item("I1")
        assert len(p.inventory) == 0


# ═══════════════════════════════════════════════════
# 冒烟测试：player_start.json 加载
# ═══════════════════════════════════════════════════

class TestPlayerStartLoading:
    """验证 player_start.json 加载后武器和物品类型正确。"""

    def test_shortbow_loaded_as_weapon(self):
        """短弓在物品栏中应是 Weapon 实例（能被 isinstance(item, Weapon) 识别）。"""
        import json, os
        from core.entity import Player, Weapon, Item

        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        with open(os.path.join(data_dir, "player_start.json"), "r", encoding="utf-8") as f:
            ps_data = json.load(f)

        # 模拟加载逻辑
        player = Player.create_fighter(name="测试", stats={"str": 8, "dex": 8, "con": 8,
                                                            "int": 8, "wis": 8, "cha": 8})
        from render.textual.app import _add_to_inventory

        for item_data in ps_data.get("inventory", []):
            if item_data.get("item_type") == "weapon":
                _add_to_inventory(player, Weapon.from_dict(item_data))
            else:
                _add_to_inventory(player, Item.from_dict(item_data))

        # 查找短弓
        shortbow = None
        for item in player.inventory:
            if item.name == "短弓":
                shortbow = item
                break
        assert shortbow is not None, "短弓应该在物品栏中"
        assert isinstance(shortbow, Weapon), "短弓必须是 Weapon 实例"
        assert shortbow.weapon_type == "ranged"
        assert shortbow.range_max == 14
        assert "two_handed" in shortbow.properties

    def test_equipment_longsword_loaded(self):
        """长剑在装备栏右手位置。"""
        import json, os
        from core.entity import Player, Weapon

        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        with open(os.path.join(data_dir, "player_start.json"), "r", encoding="utf-8") as f:
            ps_data = json.load(f)

        player = Player.create_fighter(name="测试", stats={"str": 8, "dex": 8, "con": 8,
                                                            "int": 8, "wis": 8, "cha": 8})
        for slot, item_data in ps_data.get("equipment", {}).items():
            if item_data and slot in player.equipment:
                player.equipment[slot] = Weapon.from_dict(item_data)

        longsword = player.equipment.get("right_hand")
        assert longsword is not None
        assert longsword.name == "长剑"
        assert isinstance(longsword, Weapon)
        assert longsword.weapon_type == "melee"

    def test_isinstance_check_prevents_nameerror(self):
        """验证 isinstance(item, Weapon) 在 Weapon 顶层导入后正常工作。"""
        from core.entity import Weapon
        bow = Weapon(name="短弓", weapon_type="ranged", damage="1d6",
                     damage_type="piercing", attack_stat="dex",
                     ap_cost=2, range_normal=8, range_max=14,
                     properties=["ammo", "two_handed"])
        assert isinstance(bow, Weapon)

        potion = Item(name="治疗药水", item_type="consumable", count=1)
        assert not isinstance(potion, Weapon)
