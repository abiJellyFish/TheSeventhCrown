"""物品交互逻辑测试 —— get_item_actions、ground_items 管理、丢弃/捡起流程。"""
import pytest
from core.entity import Player, Item, Weapon, Armor, Creature
from core.game_state import GameState
from core.entity import ITEM_SPACE_DEFAULT
from core.item_actions import (
    get_item_actions, find_placeable_tile, tile_space_used,
    place_on_ground, remove_from_inventory, copy_item_with_count,
    get_ground_items_at, MAX_TILE_SPACE, GROUND_ITEM_RENDER,
    _TYPE_ACTIONS, _EFFECT_LABELS,
)
from core.interact import InteractType, scan_interact_targets, _detect_ground_items


# ═══════════════════════════════════════════════════
# Item space 默认值
# ═══════════════════════════════════════════════════

class TestItemSpace:
    def test_space_from_item_type_table(self):
        """按 item_type 查表赋默认值。"""
        for item_type, expected in ITEM_SPACE_DEFAULT.items():
            item = Item(name="test", item_type=item_type)
            assert item.space == expected, f"{item_type} space should be {expected}"

    def test_space_explicit_overrides_table(self):
        """显式指定 space 时不查表。"""
        item = Item(name="test", item_type="weapon", space=5)
        assert item.space == 5

    def test_weapon_gets_space_3(self):
        w = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "damage": "1d8"})
        assert w.space == 3

    def test_armor_gets_space_4(self):
        from core.entity import Armor
        a = Armor.from_dict({"name": "布甲", "slot": "chest", "ac_bonus": 2})
        assert a.space == 4

    def test_consumable_gets_space_1(self):
        item = Item.from_dict({"name": "治疗药水", "type": "consumable", "effect": "heal"})
        assert item.space == 1

    def test_misc_gets_space_2(self):
        item = Item(name="石头", item_type="misc")
        assert item.space == 2


# ═══════════════════════════════════════════════════
# get_item_actions — 哈希表驱动
# ═══════════════════════════════════════════════════

class TestGetItemActions:
    def test_weapon_actions(self):
        w = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "damage": "1d8"})
        actions = get_item_actions(w)
        assert "装备(左手)" in actions
        assert "装备(右手)" in actions
        assert "丢弃" in actions
        assert "投掷" in actions

    def test_armor_actions(self):
        from core.entity import Armor
        a = Armor.from_dict({"name": "布甲", "slot": "chest", "ac_bonus": 2})
        actions = get_item_actions(a)
        assert "装备" in actions
        assert "丢弃" in actions
        assert "投掷" in actions
        # 护甲没有左右手之分
        assert "装备(左手)" not in actions
        assert "装备(右手)" not in actions

    def test_consumable_heal_effect(self):
        item = Item.from_dict({"name": "治疗药水", "type": "consumable", "effect": "heal"})
        actions = get_item_actions(item)
        assert "饮用(治疗)" in actions

    def test_consumable_restore_mp_effect(self):
        item = Item.from_dict({"name": "魔力药水", "type": "consumable", "effect": "restore_mp"})
        actions = get_item_actions(item)
        assert "饮用(回蓝)" in actions

    def test_consumable_restore_food_effect(self):
        item = Item.from_dict({"name": "浆果", "type": "consumable", "effect": "restore_food"})
        actions = get_item_actions(item)
        assert "食用" in actions

    def test_consumable_unknown_effect_fallback(self):
        item = Item.from_dict({"name": "神秘物品", "type": "consumable", "effect": "unknown_xyz"})
        actions = get_item_actions(item)
        assert "使用" in actions

    def test_material_no_effect(self):
        item = Item(name="木材", item_type="material")
        actions = get_item_actions(item)
        # 材料只有终端操作
        assert "丢弃" in actions
        assert "投掷" in actions
        assert "装备" not in actions

    def test_terminal_actions_always_present(self):
        """所有物品都有丢弃和投掷选项。"""
        for item_type in ["weapon", "armor", "consumable", "material", "misc"]:
            if item_type == "weapon":
                item = Weapon.from_dict({"name": "x", "weapon_type": "melee", "damage": "1d4"})
            elif item_type == "armor":
                from core.entity import Armor
                item = Armor.from_dict({"name": "x", "slot": "chest", "ac_bonus": 1})
            else:
                item = Item(name="x", item_type=item_type)
            actions = get_item_actions(item)
            assert "丢弃" in actions, f"{item_type} should have 丢弃"
            assert "投掷" in actions, f"{item_type} should have 投掷"

    def test_type_actions_table_coverage(self):
        """_TYPE_ACTIONS 覆盖所有 item_type 的操作。"""
        for item_type in _TYPE_ACTIONS:
            actions = _TYPE_ACTIONS[item_type]
            assert isinstance(actions, list)
            assert len(actions) > 0

    def test_effect_labels_table_coverage(self):
        """_EFFECT_LABELS 覆盖所有已知 effect。"""
        for effect in ["heal", "restore_mp", "restore_food"]:
            assert effect in _EFFECT_LABELS


# ═══════════════════════════════════════════════════
# 地面物品管理
# ═══════════════════════════════════════════════════

class TestGroundItemManagement:
    def test_tile_space_used_empty(self):
        items = []
        assert tile_space_used(items, 5, 5) == 0

    def test_tile_space_used_single(self):
        item = Item(name="石头", item_type="misc", space=2, count=3)
        items = [(item, (5, 5))]
        assert tile_space_used(items, 5, 5) == 6  # 2 * 3

    def test_tile_space_used_multi_item_types(self):
        i1 = Item(name="石头", item_type="misc", space=2, count=2)
        i2 = Item(name="浆果", item_type="consumable", space=1, count=5)
        items = [(i1, (5, 5)), (i2, (5, 5))]
        assert tile_space_used(items, 5, 5) == 9  # 4 + 5

    def test_tile_space_used_other_tile(self):
        item = Item(name="石头", item_type="misc", space=2, count=3)
        items = [(item, (5, 5))]
        assert tile_space_used(items, 6, 6) == 0  # different tile

    def test_place_on_ground_new(self):
        items = []
        item = Item(name="浆果", item_type="consumable", count=3, weight=0.3)
        place_on_ground(items, item, 5, 5)
        assert len(items) == 1
        assert items[0][1] == (5, 5)
        assert items[0][0].count == 3

    def test_place_on_ground_stacks_same_item(self):
        item1 = Item(name="浆果", item_type="consumable", count=3, weight=0.3)
        item2 = Item(name="浆果", item_type="consumable", count=2, weight=0.2)
        items = [(item1, (5, 5))]
        place_on_ground(items, item2, 5, 5)
        assert len(items) == 1
        assert items[0][0].count == 5
        assert items[0][0].weight == 0.5

    def test_place_on_ground_different_type_separate(self):
        item1 = Item(name="浆果", item_type="consumable", count=3, weight=0.3)
        item2 = Item(name="石头", item_type="misc", count=1, weight=0.5)
        items = [(item1, (5, 5))]
        place_on_ground(items, item2, 5, 5)
        assert len(items) == 2  # 不同类型不堆叠

    def test_find_placeable_tile_adjacent(self):
        """从玩家相邻格 BFS 查找。"""
        items = []
        item = Item(name="石头", item_type="misc", space=2, count=1)
        pos = find_placeable_tile(items, 5, 5, item, 20, 20)
        assert pos is not None
        # 起点格 (5,5) 空间不足时找相邻格
        tc, tr = pos
        assert max(abs(tc - 5), abs(tr - 5)) <= 1

    def test_find_placeable_tile_when_full(self):
        """所有格子都满时返回 None。"""
        item_big = Item(name="巨石", item_type="misc", space=MAX_TILE_SPACE + 1, count=1)
        # 周围格子是够的（空间为0），但物品本身超过 MAX_TILE_SPACE
        pos = find_placeable_tile([], 5, 5, item_big, 20, 20)
        assert pos is None

    def test_find_placeable_tile_bfs_expands(self):
        """BFS 由近到远展开。"""
        items = []
        # 填满 (5,5) 及周围一圈
        for dc in range(-1, 2):
            for dr in range(-1, 2):
                fill = Item(name="石头", item_type="misc", space=5, count=2)  # 10 per tile
                place_on_ground(items, fill, 5 + dc, 5 + dr)
        # 现在 BFS 需要扩展到更远
        small = Item(name="羽毛", item_type="misc", space=1, count=1)
        pos = find_placeable_tile(items, 5, 5, small, 20, 20)
        assert pos is not None
        tc, tr = pos
        # 应该是距离 >= 2 的格子
        dist = max(abs(tc - 5), abs(tr - 5))
        assert dist >= 2


# ═══════════════════════════════════════════════════
# remove_from_inventory
# ═══════════════════════════════════════════════════

class TestRemoveFromInventory:
    @pytest.fixture
    def player(self):
        return Player.create_fighter("测试",
            {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10})

    def test_remove_partial_stack(self, player):
        item = Item(name="浆果", item_type="consumable", count=5, weight=0.5)
        player.inventory.append(item)
        removed = remove_from_inventory(player, 0, 3)
        assert removed is not None
        assert removed.count == 3
        assert removed.name == "浆果"
        # 原物品减少
        assert player.inventory[0].count == 2
        assert player.inventory[0].weight == pytest.approx(0.2)

    def test_remove_entire_stack(self, player):
        item = Item(name="浆果", item_type="consumable", count=5, weight=0.5)
        player.inventory.append(item)
        removed = remove_from_inventory(player, 0, 5)
        assert removed is not None
        assert removed.count == 5
        assert len(player.inventory) == 0

    def test_remove_too_many_returns_none(self, player):
        item = Item(name="浆果", item_type="consumable", count=3, weight=0.3)
        player.inventory.append(item)
        removed = remove_from_inventory(player, 0, 10)
        assert removed is None
        assert len(player.inventory) == 1  # unchanged

    def test_remove_invalid_index(self, player):
        removed = remove_from_inventory(player, 999, 1)
        assert removed is None


# ═══════════════════════════════════════════════════
# copy_item_with_count
# ═══════════════════════════════════════════════════

class TestCopyItemWithCount:
    def test_copy_item(self):
        item = Item(name="浆果", item_type="consumable", count=5, weight=0.5,
                    effect="restore_food", amount="500")
        copy = copy_item_with_count(item, 3, 0.3)
        assert copy.name == "浆果"
        assert copy.item_type == "consumable"
        assert copy.count == 3
        assert copy.weight == 0.3
        assert copy.effect == "restore_food"
        # 原物品不变
        assert item.count == 5
        assert item.weight == 0.5

    def test_copy_weapon(self):
        w = Weapon.from_dict({"name": "短剑", "weapon_type": "melee", "damage": "1d6",
                               "damage_type": "piercing", "weight": 1.0, "ap_cost": 2})
        copy = copy_item_with_count(w, 1, 1.0)
        assert copy.name == "短剑"
        assert copy.item_type == "weapon"
        assert copy.damage == "1d6"
        assert copy.count == 1

    def test_copy_armor(self):
        from core.entity import Armor
        a = Armor.from_dict({"name": "皮甲", "slot": "chest", "ac_bonus": 3, "weight": 5.0})
        copy = copy_item_with_count(a, 1, 5.0)
        assert copy.name == "皮甲"
        assert copy.item_type == "armor"
        assert copy.ac_bonus == 3
        assert copy.count == 1


# ═══════════════════════════════════════════════════
# get_ground_items_at — 渲染辅助
# ═══════════════════════════════════════════════════

class TestGetGroundItemsAt:
    def test_empty_tile(self):
        assert get_ground_items_at([], 5, 5) == []

    def test_single_item(self):
        item = Item(name="浆果", item_type="consumable")
        items = [(item, (5, 5))]
        result = get_ground_items_at(items, 5, 5)
        assert len(result) == 1
        assert result[0]["item_type"] == "consumable"
        assert result[0]["count"] == 1

    def test_multiple_item_types_on_tile(self):
        i1 = Item(name="浆果", item_type="consumable", count=3)
        i2 = Item(name="短剑", item_type="weapon", count=1)
        items = [(i1, (5, 5)), (i2, (5, 5))]
        result = get_ground_items_at(items, 5, 5)
        assert len(result) == 2

    def test_ground_render_table_coverage(self):
        """GROUND_ITEM_RENDER 覆盖所有 item_type。"""
        for item_type in ITEM_SPACE_DEFAULT:
            assert item_type in GROUND_ITEM_RENDER, f"{item_type} missing from GROUND_ITEM_RENDER"

    def test_different_tile_not_returned(self):
        item = Item(name="浆果", item_type="consumable")
        items = [(item, (5, 5))]
        result = get_ground_items_at(items, 6, 6)
        assert result == []


# ═══════════════════════════════════════════════════
# GameState ground_items / item_menu_stack
# ═══════════════════════════════════════════════════

class TestGameStateItemFields:
    @pytest.fixture
    def state(self):
        p = Player.create_fighter("测试",
            {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10})
        return GameState(player=p, map_width=30, map_height=30)

    def test_ground_items_default_empty(self, state):
        assert state.ground_items == []

    def test_item_menu_stack_default_empty(self, state):
        assert state.item_menu_stack == []

    def test_push_and_pop_menu_stack(self, state):
        state.item_menu_stack.append({"type": "item_actions", "item": None, "options": []})
        assert len(state.item_menu_stack) == 1
        state.item_menu_stack.pop()
        assert len(state.item_menu_stack) == 0

    def test_find_placeable_tile_with_state(self, state):
        item = Item(name="石头", item_type="misc", space=2, count=1)
        pos = find_placeable_tile(state.ground_items, 5, 5, item,
                                  state.map.width, state.map.height)
        assert pos is not None


# ═══════════════════════════════════════════════════
# _detect_ground_items 集成测试
# ═══════════════════════════════════════════════════

class TestDetectGroundItems:
    @pytest.fixture
    def state(self):
        p = Player.create_fighter("测试",
            {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10})
        s = GameState(player=p, map_width=30, map_height=30)
        s.player_pos = (10, 10)
        return s

    def test_detect_on_player_tile(self, state):
        """玩家所在格有物品时能检测到。"""
        item = Item(name="浆果", item_type="consumable")
        state.ground_items.append((item, (10, 10)))
        targets = _detect_ground_items(state)
        assert len(targets) == 1
        assert targets[0].interact_type == InteractType.PICKUP
        assert "浆果" in targets[0].label

    def test_detect_on_adjacent_tile(self, state):
        """相邻格有物品时能检测到。"""
        item = Item(name="短剑", item_type="weapon")
        state.ground_items.append((item, (10, 9)))
        targets = _detect_ground_items(state)
        assert len(targets) == 1
        assert targets[0].pos == (10, 9)

    def test_detect_far_tile_not_detected(self, state):
        """3 格外物品不应被检测。"""
        item = Item(name="短剑", item_type="weapon")
        state.ground_items.append((item, (15, 15)))
        targets = _detect_ground_items(state)
        assert len(targets) == 0

    def test_detect_stacked_items_show_total(self, state):
        """堆叠物品在标签中显示总数量。"""
        item1 = Item(name="浆果", item_type="consumable", count=3)
        item2 = Item(name="浆果", item_type="consumable", count=2)
        state.ground_items.append((item1, (10, 9)))
        state.ground_items.append((item2, (10, 9)))
        targets = _detect_ground_items(state)
        # 同格多个条目，合并为一个目标
        assert len(targets) == 1
        assert "x5" in targets[0].label

    def test_detect_integrated_in_scan(self, state):
        """_detect_ground_items 已加入 _DETECTORS。"""
        item = Item(name="药水", item_type="consumable")
        state.ground_items.append((item, (10, 9)))
        all_targets = scan_interact_targets(state)
        assert any(t.interact_type == InteractType.PICKUP for t in all_targets)

    def test_detect_no_items(self, state):
        targets = _detect_ground_items(state)
        assert targets == []


# ═══════════════════════════════════════════════════
# _TYPE_ACTIONS / _EFFECT_LABELS 完整性
# ═══════════════════════════════════════════════════

class TestActionTableCompleteness:
    """确保哈希表覆盖所有已知类型，新增类型只需加一行。"""

    def test_type_actions_all_item_types(self):
        """_TYPE_ACTIONS 键包含所有相关的 item_type。"""
        assert "weapon" in _TYPE_ACTIONS
        assert "armor" in _TYPE_ACTIONS

    def test_effect_labels_non_empty(self):
        assert len(_EFFECT_LABELS) >= 3
        for effect, label in _EFFECT_LABELS.items():
            assert isinstance(effect, str) and effect
            assert isinstance(label, str) and label
