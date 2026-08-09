"""app.py 物品栏/装备函数测试 —— 防止 NameError 等回归。"""

import pytest
from unittest.mock import MagicMock

from core.entity import Player, Weapon, Item


# ═══════════════════════════════════════════════════
# 模块级 fixtures
# ═══════════════════════════════════════════════════

@pytest.fixture
def state():
    """返回模拟的 game_state，player 为真实 Player 对象。"""
    s = MagicMock()
    s.in_combat = False
    s.interact_phase = ""
    s.combat_phase = "idle"
    s.observe_mode = False
    s.interact_target = None
    s.interact_targets = []
    s.shop_data = None
    s.player = Player.create_fighter(name="测试", stats={"str": 8, "dex": 8, "con": 8,
                                                          "int": 8, "wis": 8, "cha": 8})
    s.player.inventory = []
    for slot in s.player.equipment:
        s.player.equipment[slot] = None
    return s


@pytest.fixture
def app(state):
    """构造未初始化的 MVPApp 实例用于测试。"""
    from unittest.mock import patch
    from render.textual.app import MVPApp
    with patch.object(MVPApp, '__init__', lambda self: None):
        app = MVPApp.__new__(MVPApp)
    app._state = state
    app._act_log = MagicMock()
    rp = MagicMock()
    rp.view_mode = "default"
    app._right_panel = rp
    app._map_view = MagicMock()
    app._input_bar = MagicMock()
    return app


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
                      properties=["ammo"])

    def test_equip_to_empty_hand(self, app, state, shortbow):
        """空手状态下装备武器 → 默认装备到左手。"""
        p = state.player
        p.inventory = [shortbow]
        p.equipment["left_hand"] = None
        p.equipment["right_hand"] = None

        app._equip_to_hand(shortbow, 0)
        assert p.equipment["left_hand"] is shortbow
        assert len(p.inventory) == 0

    def test_equip_swaps_with_existing_weapon(self, app, state, shortbow, longsword):
        """左手已有武器，装备新武器应到右手（左→右顺序）。"""
        p = state.player
        p.inventory = [shortbow]
        p.equipment["left_hand"] = longsword
        p.equipment["right_hand"] = None

        app._equip_to_hand(shortbow, 0)
        # 左手被占 → 装备到右手
        assert p.equipment["right_hand"] is shortbow
        assert p.equipment["left_hand"] is longsword
        assert len(p.inventory) == 0

    def test_use_item_weapon_triggers_equip(self, app, state, shortbow):
        """_use_item 识别 Weapon 类型并调用装备逻辑 → 默认左手。"""
        p = state.player
        p.inventory = [shortbow]
        p.equipment["left_hand"] = None
        p.equipment["right_hand"] = None
        p.ap = 6

        app._use_item("I1")
        assert p.equipment["left_hand"] is shortbow
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
        assert "ammo" in shortbow.properties

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
                     properties=["ammo"])
        assert isinstance(bow, Weapon)

        potion = Item(name="治疗药水", item_type="consumable", count=1)
        assert not isinstance(potion, Weapon)


# ═══════════════════════════════════════════════════
# 视图注册表
# ═══════════════════════════════════════════════════

class TestViewRegistry:
    """验证 VIEW_DEFS 的完整性和正确性。"""

    def test_all_view_keys_are_sets(self, app):
        """每个视图的 keys 是可迭代集合，commands 是 dict。"""
        for name, vdef in app.VIEW_DEFS.items():
            assert hasattr(vdef["keys"], '__iter__'), f"{name}.keys 应为可迭代集合"
            assert isinstance(vdef["commands"], dict), f"{name}.commands 应为 dict"

    def test_explore_has_all_movement_keys(self, app):
        """探索视图包含方向键以外的所有动作键。"""
        keys = app.VIEW_DEFS["explore"]["keys"]
        for k in ("0", "1", "X", "C", "I", "A", "S", "g", "r", "R"):
            assert k in keys

    def test_trading_has_bs_commands(self, app):
        """交易视图注册了 B 和 S 命令。"""
        cmds = app.VIEW_DEFS["trading"]["commands"]
        assert "B" in cmds
        assert "S" in cmds

    def test_inventory_has_iuw_commands(self, app):
        """物品栏注册了 I/U/W 命令。"""
        cmds = app.VIEW_DEFS["inventory"]["commands"]
        assert "I" in cmds
        assert "U" in cmds
        assert "W" in cmds

    def test_get_active_views_explore(self, app, state):
        """探索模式 → 活跃视图为 explore。"""
        state.interact_phase = ""
        state.combat_phase = "idle"
        state.in_combat = False
        state.observe_mode = False
        views = app._get_active_views()
        assert "explore" in views

    def test_get_active_views_trading_plus_inventory(self, app, state):
        """交易 + 物品栏同时打开 → 两个视图都活跃。"""
        state.interact_phase = "trading"
        state.combat_phase = "idle"
        app._right_panel.view_mode = "inventory"
        views = app._get_active_views()
        assert "trading" in views
        assert "inventory" in views

    def test_get_active_views_combat_sub_phase(self, app, state):
        """战斗子阶段 → 对应视图活跃。"""
        state.interact_phase = ""
        state.combat_phase = "select_action"
        state.in_combat = True
        views = app._get_active_views()
        assert "combat_select_action" in views

    def test_command_merge_trading_inventory(self, app, state):
        """交易 + 物品栏时，命令表包含两者的前缀。"""
        state.interact_phase = "trading"
        state.combat_phase = "idle"
        app._right_panel.view_mode = "inventory"
        all_cmds = {}
        for vn in app._get_active_views():
            vdef = app.VIEW_DEFS.get(vn, {})
            all_cmds.update(vdef.get("commands", {}))
        # trading 的 B/S + inventory 的 I/U/W 都应该在
        for prefix in ("B", "S", "I", "U", "W"):
            assert prefix in all_cmds, f"缺少命令前缀 {prefix}"

    def test_no_command_conflicts(self, app):
        """可同时活跃的视图之间，同一命令前缀不冲突。"""
        # trading + inventory 可能同时活跃，验证 B/S 与 I/U/W 不冲突
        trading_cmds = set(app.VIEW_DEFS["trading"]["commands"].keys())
        inv_cmds = set(app.VIEW_DEFS["inventory"]["commands"].keys())
        overlap = trading_cmds & inv_cmds
        for prefix in overlap:
            t_method = app.VIEW_DEFS["trading"]["commands"][prefix]
            i_method = app.VIEW_DEFS["inventory"]["commands"][prefix]
            assert t_method == i_method, f"trading 和 inventory 命令 {prefix} 冲突"
        # 各视图内部 commands 的 prefix 应指向可调用的方法
        for name, vdef in app.VIEW_DEFS.items():
            for prefix, method_name in vdef["commands"].items():
                assert hasattr(app, method_name), f"{name}.commands[{prefix}] → {method_name} 方法不存在"
