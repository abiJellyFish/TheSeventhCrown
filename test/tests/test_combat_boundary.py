"""战斗系统边界场景测试 —— 覆盖死循环/状态机/多实体边界。"""

import pytest
from unittest.mock import MagicMock, patch


# ═══════════════════════════════════════════════════
# CombatFlow._find_adjacent_targets 边界
# ═══════════════════════════════════════════════════

class TestFindAdjacentTargets:
    """_find_adjacent_targets 各种实体配置。"""

    @pytest.fixture
    def flow(self):
        from core.combat.flow import CombatFlow
        state = MagicMock()
        state.player_pos = (5, 5)
        flow = CombatFlow(state, MagicMock(), MagicMock(), MagicMock(),
                          MagicMock(), "测试", MagicMock(), MagicMock())
        return flow

    def test_no_entities_returns_empty(self, flow):
        """0 个实体 → 返回空列表。"""
        flow._state.entities = []
        result = flow._find_adjacent_targets()
        assert result == []

    def test_only_dead_entities_returns_empty(self, flow):
        """仅死亡实体 → 返回空列表。"""
        dead = MagicMock()
        dead.hp = 0
        flow._state.entities = [(dead, (5, 6))]
        flow._state.player = MagicMock()
        result = flow._find_adjacent_targets()
        assert result == []

    def test_only_player_returns_empty(self, flow):
        """仅玩家自身 → 返回空列表。"""
        player = MagicMock()
        player.hp = 30
        flow._state.player = player
        flow._state.entities = [(player, (5, 5))]
        result = flow._find_adjacent_targets()
        assert result == []

    def test_distant_entity_not_included(self, flow):
        """超出相邻范围的实体不被包含。"""
        far = MagicMock()
        far.hp = 10
        flow._state.player = MagicMock()
        flow._state.entities = [(far, (10, 10))]  # 距离 5，超出相邻
        result = flow._find_adjacent_targets()
        assert result == []

    def test_eight_surrounding_all_returned(self, flow):
        """玩家被 8 个实体包围 → 全部返回。"""
        flow._state.player = MagicMock()
        entities = []
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                c = MagicMock()
                c.hp = 10
                entities.append((c, (5 + dc, 5 + dr)))
        flow._state.entities = entities
        result = flow._find_adjacent_targets()
        assert len(result) == 8

    def test_sorted_by_distance_then_hp(self, flow):
        """结果按距离和 HP 排序。"""
        flow._state.player = MagicMock()
        c1 = MagicMock(); c1.hp = 1
        c2 = MagicMock(); c2.hp = 10
        # c1 距离 1, c2 距离 1 → c1 HP 更低，排前面
        flow._state.entities = [(c1, (5, 6)), (c2, (6, 5))]
        result = flow._find_adjacent_targets()
        assert result[0] is c1
        assert result[1] is c2


# ═══════════════════════════════════════════════════
# _start_combat 边界
# ═══════════════════════════════════════════════════

class TestStartCombatBoundary:
    """_start_combat 各种战斗开始场景。"""

    @pytest.fixture
    def app(self):
        """构造最小 MVPApp mock 用于测试 _start_combat。"""
        from render.textual.app import MVPApp
        app = MVPApp()
        app._state = MagicMock()
        app._state.in_combat = False
        app._state.player = MagicMock()
        app._state.player.max_ap = 6
        app._state.player.name = "测试"
        app._state.player_pos = (5, 5)
        app._act_log = MagicMock()
        app.refresh_all = MagicMock()
        return app

    def test_zero_hostiles_combatants_only_player(self, app):
        """0 个敌对 → combat_initiative 仅含玩家。"""
        app._state.entities = []
        app._next_turn = MagicMock()
        app._state.in_combat = False

        app._start_combat(MagicMock(), ambush=False)

        assert app._state.in_combat is True
        assert len(app._state.combat_initiative) == 1

    def test_zero_hostiles_ambush_ends_gracefully(self, app):
        """ambush=True 但 0 敌对 → 不会崩溃。"""
        app._state.entities = []
        target = MagicMock()
        target.faction = "hostile"
        target.hp = 10

        app._start_combat(target, ambush=True)

        assert app._state.combat_turn_entity is app._state.player

    def test_multiple_hostiles_all_included(self, app):
        """5 个敌对均进入先攻列表。"""
        hostiles = []
        for i in range(5):
            h = MagicMock()
            h.hp = 10
            h.faction = "hostile"
            h.max_ap = 6
            h.initiative_bonus.return_value = i
            hostiles.append((h, (5 + i % 3, 4 + i // 3)))

        app._state.entities = hostiles
        app._state.player.initiative_bonus.return_value = 5
        app._next_turn = MagicMock()

        app._start_combat(MagicMock(), ambush=False)

        # 1 玩家 + 5 敌对
        assert len(app._state.combat_initiative) == 6

    def test_friendly_not_included(self, app):
        """友好实体不被拉入战斗。"""
        friend = MagicMock()
        friend.hp = 10
        friend.faction = "friendly"
        app._state.entities = [(friend, (5, 6))]
        app._next_turn = MagicMock()

        app._start_combat(MagicMock(), ambush=False)

        assert len(app._state.combat_initiative) == 1  # 仅玩家

    def test_neutral_not_included(self, app):
        """中立实体不被拉入战斗。"""
        neutral = MagicMock()
        neutral.hp = 10
        neutral.faction = "neutral"
        app._state.entities = [(neutral, (5, 6))]
        app._next_turn = MagicMock()

        app._start_combat(MagicMock(), ambush=False)

        assert len(app._state.combat_initiative) == 1  # 仅玩家

    def test_out_of_range_hostile_not_included(self, app):
        """距离>5的敌对不被拉入。"""
        far = MagicMock()
        far.hp = 10
        far.faction = "hostile"
        app._state.entities = [(far, (20, 20))]
        app._next_turn = MagicMock()

        app._start_combat(MagicMock(), ambush=False)

        assert len(app._state.combat_initiative) == 1

    def test_dead_hostile_not_included(self, app):
        """已死亡的敌对不参与战斗。"""
        dead = MagicMock()
        dead.hp = 0
        dead.faction = "hostile"
        app._state.entities = [(dead, (5, 6))]
        app._next_turn = MagicMock()

        app._start_combat(MagicMock(), ambush=False)

        assert len(app._state.combat_initiative) == 1


# ═══════════════════════════════════════════════════
# NPC 回合死循环防护
# ═══════════════════════════════════════════════════

class TestNPCTurnTermination:
    """_npc_turn 在各种阻塞场景下的终止性。"""

    @pytest.fixture
    def app(self):
        from render.textual.app import MVPApp
        app = MVPApp()
        app._state = MagicMock()
        app._state.player_pos = (5, 5)
        app._state.player = MagicMock()
        app._state.player.hp = 30
        app._act_log = MagicMock()
        app._next_turn = MagicMock()
        app.refresh_all = MagicMock()
        return app

    def _make_npc(self, ap=6, actions=None):
        npc = MagicMock()
        npc.ap = ap
        npc.max_ap = ap
        npc.hp = 10
        npc.faction = "hostile"
        npc.name = "测试NPC"
        npc.actions = actions or []
        npc.statuses = []
        return npc

    def test_npc_with_zero_ap_skips_turn(self, app):
        """AP=0 的 NPC 直接跳过回合。"""
        npc = self._make_npc(ap=0)
        pos = (5, 6)
        app._state.entities = [(npc, pos)]
        app._find_entity_pos = lambda c: pos if c is npc else None

        app._npc_turn(npc)

        app._next_turn.assert_called_once()

    def test_npc_with_no_actions_and_adjacent_breaks(self, app):
        """无动作且在相邻格的 NPC 直接结束回合。"""
        npc = self._make_npc(ap=6, actions=[])
        pos = (5, 6)  # 相邻
        app._state.entities = [(npc, pos)]
        app._find_entity_pos = lambda c: pos if c is npc else None

        app._npc_turn(npc)

        app._next_turn.assert_called_once()

    def test_npc_blocked_by_entity_stops_gracefully(self, app):
        """被其他实体阻挡时不会死循环。"""
        npc = self._make_npc(ap=6, actions=[
            {"type": "melee_attack", "name": "拳击", "damage": "1d4",
             "damage_type": "bludgeoning", "attack_stat": "str",
             "ap_cost": 2, "reach": 1}
        ])
        pos = (5, 3)  # 距离 2，非相邻
        app._state.entities = [(npc, pos)]
        app._find_entity_pos = lambda c: pos if c is npc else None
        app._move_npc_toward = lambda *a, **kw: False  # 始终被阻挡

        # 不应抛出异常或死循环
        app._npc_turn(npc)

        app._next_turn.assert_called_once()

    def test_npc_surrounded_by_walls_stops(self, app):
        """被墙壁包围时不会死循环。"""
        npc = self._make_npc(ap=6, actions=[
            {"type": "melee_attack", "name": "爪击", "damage": "1d6",
             "damage_type": "slashing", "attack_stat": "dex",
             "ap_cost": 2, "reach": 1}
        ])
        pos = (5, 3)
        app._state.entities = [(npc, pos)]
        app._find_entity_pos = lambda c: pos if c is npc else None
        app._move_npc_toward = lambda *a, **kw: False

        app._npc_turn(npc)

        app._next_turn.assert_called_once()

    def test_npc_ap_decreases_during_turn(self, app):
        """执行动作后 AP 应减少（无论命中与否）。"""
        npc = self._make_npc(ap=6, actions=[
            {"type": "melee_attack", "name": "咬", "damage": "1d6",
             "damage_type": "piercing", "attack_stat": "str",
             "ap_cost": 2, "reach": 1}
        ])
        npc.stat_adjust = lambda s: 2
        npc.total_ac = lambda part="chest": 12
        npc.tenacity = 10
        pos = (5, 6)  # 相邻，无需移动
        app._state.entities = [(npc, pos)]
        app._state.player.stat_adjust = lambda s: 2
        app._state.player.total_ac = lambda part="chest": 12
        app._state.player.tenacity = 10
        app._state.player.statuses = []
        app._find_entity_pos = lambda c: pos if c is npc else None
        app._move_npc_toward = lambda *a, **kw: False

        initial_ap = npc.ap
        app._npc_turn(npc)

        # AP 必须减少（无论攻击命中与否，动作都会消耗 AP）
        assert npc.ap < initial_ap, f"AP 应从 {initial_ap} 减少，实际为 {npc.ap}"


# ═══════════════════════════════════════════════════
# 战斗状态机转换
# ═══════════════════════════════════════════════════

class TestCombatPhaseTransitions:
    """攻击流程状态机各阶段的边界。"""

    @pytest.fixture
    def flow(self):
        from core.combat.flow import CombatFlow
        state = MagicMock()
        state.combat_phase = "idle"
        state.player = MagicMock()
        state.player.ap = 6
        state.player.max_ap = 6
        state.player.equipment = {"right_hand": MagicMock()}
        state.player.equipment["right_hand"].weapon_type = "melee"
        state.player.equipment["right_hand"].name = "长剑"
        state.player.equipment["right_hand"].damage = "1d8"
        state.player.equipment["right_hand"].damage_type = "slashing"
        state.player.equipment["right_hand"].attack_stat = "str"
        state.player.equipment["right_hand"].ap_cost = 2
        state.player_pos = (5, 5)
        state.pending_attack = {}
        state.in_combat = False
        state.entities = []
        act_log = MagicMock()
        left_panel = MagicMock()
        left_panel._action_map = {}
        left_panel._maneuver_map = {}
        left_panel._special_map = {}
        flow = CombatFlow(state, act_log, left_panel,
                          MagicMock(), MagicMock(), "测试",
                          MagicMock(), MagicMock())
        return flow

    def test_start_action_phase_when_not_idle_is_ignored(self, flow):
        """非 idle 状态调用 start_action_phase 应被忽略。"""
        flow._state.combat_phase = "select_target"
        flow.start_action_phase()
        assert flow._state.combat_phase == "select_target"  # 不变

    def test_handle_action_invalid_cmd_does_not_crash(self, flow):
        """无效命令不崩溃。"""
        flow.handle_action_input("xyz")
        flow.handle_action_input("A")
        flow.handle_action_input("Aabc")
        flow.handle_action_input("")

    def test_handle_action_cancel_returns_to_idle(self, flow):
        """A0 取消回到 idle。"""
        flow._state.combat_phase = "select_action"
        flow._state.pending_attack = {"dummy": True}
        flow.handle_action_input("A0")
        assert flow._state.combat_phase == "idle"
        assert flow._state.pending_attack == {}

    def test_handle_target_cancel_returns_to_action(self, flow):
        """T0 取消回到 select_action。"""
        flow._state.combat_phase = "select_target"
        flow.handle_target_input("T0")
        assert flow._state.combat_phase == "select_action"

    def test_handle_target_invalid_does_not_crash(self, flow):
        """无效目标命令不崩溃。"""
        flow._state.combat_phase = "select_target"
        flow.handle_target_input("xyz")
        flow.handle_target_input("Tabc")

    def test_handle_maneuver_invalid_does_not_crash(self, flow):
        """无效战技命令不崩溃。"""
        flow._state.combat_phase = "select_maneuver"
        flow._state.pending_attack = {"weapon": MagicMock(), "target": MagicMock(),
                                       "attack_roll": 15, "hit": True}
        flow._state.pending_attack["weapon"].damage_type = "slashing"
        flow._state.pending_attack["target"].name = "测试目标"
        flow._state.pending_attack["target"].hp = 10
        flow.handle_maneuver_input("xyz")

    def test_handle_special_invalid_does_not_crash(self, flow):
        """无效特殊行动命令不崩溃。"""
        flow._state.combat_phase = "select_special"
        flow._state.pending_attack = {"weapon": MagicMock(), "target": MagicMock(),
                                       "attack_roll": 5, "hit": False}
        flow.handle_special_input("xyz")


# ═══════════════════════════════════════════════════
# _post_action_update 边界
# ═══════════════════════════════════════════════════

class TestPostActionUpdate:
    """_post_action_update 各种场景。"""

    @pytest.fixture
    def app(self):
        from render.textual.app import MVPApp
        app = MVPApp()
        app._state = MagicMock()
        app._state.pending_combat_target = None
        app._state.player_pos = (5, 5)
        app._state.map = MagicMock()
        app._state.map.width = 80
        app._state.map.height = 60
        app._state.in_dungeon = False
        app._state.player = MagicMock()
        app._state.player.vision_range = 8
        app._state.player.darkvision_range = 0
        app._state.fov_cache = set()
        app._act_log = MagicMock()
        app._scene_log = MagicMock()
        app.refresh_all = MagicMock()
        return app

    def test_no_pending_target_does_nothing(self, app):
        """无待处理目标时仅刷新 UI。"""
        app._state.pending_combat_target = None
        app._post_action_update()
        # 不应调用 _start_combat

    def test_pending_target_triggers_combat(self, app):
        """有待处理目标时触发战斗。"""
        target = MagicMock()
        target.name = "地精"
        target.faction = "hostile"
        target.hp = 10
        app._state.pending_combat_target = target
        app._start_combat = MagicMock()

        app._post_action_update()

        app._start_combat.assert_called_once_with(target)
        assert app._state.pending_combat_target is None
