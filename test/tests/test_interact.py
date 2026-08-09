"""交互系统测试 —— scan_interact_targets 扫描 + 类型判定。"""

import pytest
from core.game_state import GameState
from core.entity import Player, Creature, StatusEffect
from core.grid import Grid
from core.movement import Terrain
from core.interact import (
    InteractType, InteractTarget, scan_interact_targets,
    _detect_creatures, _detect_doors, _detect_beds, _detect_bushes, _detect_entrances,
    CREATURE_TRAIT_FLAGS,
)


def _make_state():
    """构造含玩家的最小 GameState。"""
    p = Player(name="测试玩家", char_class="fighter", faction="friendly")
    state = GameState(player=p, map_width=20, map_height=20)
    state.player_pos = (10, 10)
    return state


# ═══════════════════════════════════
# scan_interact_targets 集成测试
# ═══════════════════════════════════

class TestScanInteractTargets:

    def test_no_targets_empty_area(self):
        """空地无任何可交互目标 → 返回空列表。"""
        state = _make_state()
        targets = scan_interact_targets(state)
        assert targets == []

    def test_detect_friendly_creature(self):
        """相邻格友好生物 → TALK 类型。"""
        state = _make_state()
        c = Creature(name="村民", faction="friendly", hp=10, max_hp=10)
        state.add_entity(c, (10, 9))
        targets = scan_interact_targets(state)
        assert len(targets) == 1
        t = targets[0]
        assert t.interact_type == InteractType.TALK
        assert t.creature is c
        assert t.label == "村民"

    def test_detect_hostile_creature(self):
        """相邻格敌对生物 → 仍然 TALK（由 app.py 分发到开战）。"""
        state = _make_state()
        c = Creature(name="地精打手", faction="hostile", hp=10, max_hp=10)
        state.add_entity(c, (10, 9))
        targets = scan_interact_targets(state)
        assert len(targets) == 1
        assert targets[0].interact_type == InteractType.TALK

    def test_detect_corpse(self):
        """相邻格尸体 → LOOT 类型。"""
        state = _make_state()
        c = Creature(name="地精打手", faction="hostile", hp=0, max_hp=20)
        state.add_entity(c, (11, 10))
        targets = scan_interact_targets(state)
        assert len(targets) == 1
        t = targets[0]
        assert t.interact_type == InteractType.LOOT
        assert "尸体" in t.label

    def test_detect_door(self):
        """相邻格门 → OPEN 类型。"""
        state = _make_state()
        door_pos = (10, 9)
        state.door_states[door_pos] = False
        state.map[door_pos] = Terrain.WALL
        targets = scan_interact_targets(state)
        assert len(targets) == 1
        t = targets[0]
        assert t.interact_type == InteractType.OPEN
        assert "关闭" in t.label

    def test_detect_open_door(self):
        """相邻格打开的门 → OPEN 类型，标签不同。"""
        state = _make_state()
        door_pos = (10, 9)
        state.door_states[door_pos] = True
        state.map[door_pos] = Terrain.PASSABLE
        targets = scan_interact_targets(state)
        t = targets[0]
        assert "打开" in t.label
        assert t.extra["is_open"] is True

    def test_detect_bed(self):
        """相邻格床 → REST 类型。"""
        state = _make_state()
        state.bed_positions.add((11, 10))
        targets = scan_interact_targets(state)
        assert len(targets) == 1
        assert targets[0].interact_type == InteractType.REST

    def test_detect_bush(self):
        """相邻格灌木（DIFFICULT 非石头）→ PICK 类型。"""
        state = _make_state()
        state.map[10, 9] = Terrain.DIFFICULT
        targets = scan_interact_targets(state)
        assert len(targets) == 1
        assert targets[0].interact_type == InteractType.PICK

    def test_stone_not_detected_as_bush(self):
        """石头（DIFFICULT 但在 stone_positions 中）不被检测为灌木。"""
        state = _make_state()
        state.map[10, 9] = Terrain.DIFFICULT
        state.stone_positions.add((10, 9))
        targets = scan_interact_targets(state)
        # 石头不应被检测为 PICK
        pick_targets = [t for t in targets if t.interact_type == InteractType.PICK]
        assert len(pick_targets) == 0

    def test_detect_entrance(self):
        """自身格为地城入口 → ENTER 类型。"""
        state = _make_state()
        state.dungeon_entrance = (10, 10)
        state.player_pos = (10, 10)
        targets = scan_interact_targets(state)
        enter_targets = [t for t in targets if t.interact_type == InteractType.ENTER]
        assert len(enter_targets) == 1
        assert enter_targets[0].extra["direction"] == "enter"

    def test_detect_exit(self):
        """自身格为地城出口（在地城中）→ ENTER 类型，direction=exit。"""
        state = _make_state()
        state.in_dungeon = True
        state.dungeon_exit = (10, 10)
        state.player_pos = (10, 10)
        targets = scan_interact_targets(state)
        enter_targets = [t for t in targets if t.interact_type == InteractType.ENTER]
        assert len(enter_targets) == 1
        assert enter_targets[0].extra["direction"] == "exit"

    def test_multiple_targets(self):
        """多个可交互目标 → 全部被检测到。"""
        state = _make_state()
        c = Creature(name="商人", faction="friendly", hp=10, max_hp=10, traits=["merchant"])
        state.add_entity(c, (10, 9))
        state.map[11, 10] = Terrain.DIFFICULT  # 灌木
        targets = scan_interact_targets(state)
        assert len(targets) >= 2
        types = {t.interact_type for t in targets}
        assert InteractType.TALK in types
        assert InteractType.PICK in types

    def test_merchant_has_can_trade_flag(self):
        """带 'merchant' trait 的生物 → extra 含 can_trade=True。"""
        state = _make_state()
        c = Creature(name="商人", faction="friendly", hp=10, max_hp=10, traits=["merchant"])
        state.add_entity(c, (10, 9))
        targets = scan_interact_targets(state)
        t = targets[0]
        assert t.extra.get("can_trade") is True

    def test_creature_2_tiles_away_not_detected(self):
        """距离 > 1 的生物不被检测。"""
        state = _make_state()
        c = Creature(name="村民", faction="friendly", hp=10, max_hp=10)
        state.add_entity(c, (12, 10))  # Chebyshev 距离 = 2
        targets = scan_interact_targets(state)
        creature_targets = [t for t in targets if t.creature is not None]
        assert len(creature_targets) == 0

    def test_player_not_detected_as_target(self):
        """玩家自身不被列为可交互目标。"""
        state = _make_state()
        # 玩家在同位置不应被检测到
        targets = scan_interact_targets(state)
        for t in targets:
            if t.creature is not None:
                assert t.creature is not state.player


# ═══════════════════════════════════
# CREATURE_TRAIT_FLAGS 扩展性
# ═══════════════════════════════════

class TestCreatureTraitFlags:

    def test_merchant_flag_registered(self):
        """merchant trait 已注册为 can_trade。"""
        assert "merchant" in CREATURE_TRAIT_FLAGS
        assert CREATURE_TRAIT_FLAGS["merchant"] == "can_trade"

    def test_unknown_trait_ignored(self):
        """未知 trait 不影响检测结果。"""
        state = _make_state()
        c = Creature(name="铁匠", faction="friendly", hp=10, max_hp=10,
                     traits=["blacksmith"])  # 未注册的 trait
        state.add_entity(c, (10, 9))
        targets = scan_interact_targets(state)
        t = targets[0]
        # 仍然是 TALK，但不含 can_trade
        assert t.interact_type == InteractType.TALK
        assert t.extra.get("can_trade") is None


# ═══════════════════════════════════
# 各个检测器独立测试
# ═══════════════════════════════════

class TestDetectors:

    def test_detect_creatures_alive_and_dead(self):
        """同时有活着的和死亡的生物。"""
        state = _make_state()
        alive = Creature(name="村民", faction="friendly", hp=10, max_hp=10)
        dead = Creature(name="地精", faction="hostile", hp=0, max_hp=20)
        state.add_entity(alive, (10, 9))
        state.add_entity(dead, (11, 10))
        results = _detect_creatures(state)
        assert len(results) == 2
        types = {t.interact_type for t in results}
        assert InteractType.TALK in types
        assert InteractType.LOOT in types

    def test_detect_doors_returns_both_states(self):
        """同时有开着的和关着的门。"""
        state = _make_state()
        state.door_states[(10, 9)] = True
        state.door_states[(11, 10)] = False
        results = _detect_doors(state)
        assert len(results) == 2

    def test_detect_beds_single(self):
        """检测到一个床。"""
        state = _make_state()
        state.bed_positions.add((10, 9))
        results = _detect_beds(state)
        assert len(results) == 1
        assert results[0].interact_type == InteractType.REST

    def test_detect_bushes_skips_stone(self):
        """灌木检测跳过石头。"""
        state = _make_state()
        state.map[10, 9] = Terrain.DIFFICULT  # 普通灌木
        state.map[11, 10] = Terrain.DIFFICULT
        state.stone_positions.add((11, 10))   # 石头
        results = _detect_bushes(state)
        assert len(results) == 1
        assert results[0].pos == (10, 9)

    def test_detect_bushes_out_of_bounds(self):
        """边界外的格子不检测。"""
        state = _make_state()
        state.player_pos = (0, 0)
        results = _detect_bushes(state)
        # 所有检查都在边界内
        for r in results:
            assert state.map.within_bounds(r.pos[0], r.pos[1])

    def test_detect_entrances_none(self):
        """不在入口 → 无 ENTER 目标。"""
        state = _make_state()
        results = _detect_entrances(state)
        assert len(results) == 0
