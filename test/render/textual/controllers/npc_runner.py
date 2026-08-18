"""NPC 战斗行动执行 —— 移动逼近、近战、特殊行动、AP 合计、索敌。"""
import json
import os
import random
from core.game_state import GameState, _move_ap_cost
from core.entity import Entity, Weapon, are_hostile
import core.entity as ent
from core.movement import Terrain, find_path
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import (hit_check, roll_damage, reduce_tenacity,
    apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack,
    miss_message, cover_message, normalize_damage_type)
from core.combat.flow import CombatFlow
from core.map.generation import build_world, build_dungeon
from core.dice import roll_d20, check_dc, roll_2d6
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader, _load_dialogues, _load_scene_actions
from core.save.database import SaveManager
from core.interact import InteractType, scan_interact_targets
from core.trade import (load_shop, trade_buy, trade_sell, price_to_text,
    copper_to_currency, shop_gold_text, player_receive, _build_item_cache,
    resolve_items, _load_item_by_key)
from core.item_actions import (get_item_actions, find_placeable_tile,
    place_on_ground, remove_from_inventory as item_remove_from_inventory,
    copy_item_with_count, get_throw_range, get_throw_max_range,
    tile_space_used, MAX_TILE_SPACE)
from core.loot import _add_to_inventory
from render.textual.fov import _update_fov



class NpcRunnerMixin:

    def _move_npc_toward(self, npc: Entity, nc: int, nr: int,
                         tc: int, tr: int) -> bool:
        """NPC 向目标坐标移动一格（A* 寻路 + 简单 fallback）。"""
        # 尝试 A* 寻路
        path = find_path(self._state.map, self._state.entities,
                         (nc, nr), (tc, tr),
                         ground_items=self._state.ground_items,
                         door_positions=set(self._state.door_states.keys()))
        if path and len(path) >= 2:
            # path[0] = 起点, path[1] = 下一步
            nx, ny = path[1]
            if self._state.move_entity(npc, nc, nr, nx, ny):
                return True

        # A* 失败或不可达，fallback 到简单朝向移动
        dc = 1 if tc > nc else (-1 if tc < nc else 0)
        dr = 1 if tr > nr else (-1 if tr < nr else 0)
        for try_dc, try_dr in [(dc, dr), (dc, 0), (0, dr)]:
            nx, ny = nc + try_dc, nr + try_dr
            if self._state.move_entity(npc, nc, nr, nx, ny):
                return True
        return False

    def _npc_melee_attack(self, npc: Entity, action: dict,
                           target: Entity) -> None:
        """NPC 执行近战攻击，按 MVP2.md 武器数据结算。"""
        weapon_name = action.get("weapon", "徒手打击")
        damage_str = action.get("damage", "1d4")
        damage_type = action.get("damage_type", "bludgeoning")
        attack_stat_name = action.get("attack_stat", "str")
        ap_cost = action.get("ap_cost", 20)

        npc.ap -= ap_cost
        weapon = Weapon(
            name=weapon_name, damage=damage_str,
            damage_type=damage_type, attack_stat=attack_stat_name,
            ap_cost=ap_cost)

        npc_pos = self._state.get_entity_pos(npc)
        target_pos = self._state.get_entity_pos(target)
        hidden = False
        out_of_sight = False
        if npc_pos and target_pos:
            hidden = self._state._is_hidden_to(target, npc, npc_pos)
            ddist = max(abs(target_pos[0] - npc_pos[0]), abs(target_pos[1] - npc_pos[1]))
            out_of_sight = ddist > 1 and not self._state._observer_can_see(target, npc_pos)
        result = resolve_attack(
            npc, target, weapon,
            attacker_pos=npc_pos, target_pos=target_pos,
            grid=self._state.map,
            ground_items=self._state.ground_items,
            hidden=hidden, out_of_sight=out_of_sight,
        )
        if npc.has_status("assisted"):
            npc.remove_status("assisted")
        if result["hit"]:
            self._act_log.add(
                f"{npc.name}使用{weapon_name}击中了{target.name}，"
                f"造成 {result['damage']} 点{damage_type}伤害")
            if target is self._state.player and target.is_dead:
                self._act_log.add(f"{self._pn} 被击杀了!")
            elif target is self._state.player and target.has_status("濒死"):
                self._act_log.add(f"{self._pn} 倒地不起，正在死亡边缘挣扎! [R]长休/急救")
        else:
            dmg_type = damage_type  # 失手/掩体风味文案用武器原始类型（伤害数值已转钝击）
            if result.get("blocked_by_cover"):
                self._act_log.add(
                    f"{npc.name}使用{weapon_name}攻击{target.name}，"
                    f"{cover_message(dmg_type)} (roll={result['roll']})")
            else:
                self._act_log.add(
                    miss_message(npc.name, target.name, dmg_type)
                    + f" (roll={result['roll']})")

    def _npc_special_action(self, npc: Entity, action: dict, target,
                             nc: int, nr: int, tc: int, tr: int) -> None:
        """NPC 执行特殊动作，按 MVP2.md 描述结算效果。"""
        name = action.get("name", "特殊动作")
        ap_cost = action.get("ap_cost", 30)
        npc.ap -= ap_cost

        if "扑倒" in name:
            # DC12 敏捷豁免，失败则倒地
            save_roll = roll_d20() + target.stat_adjust("dex")
            if save_roll < 12:
                if not target.has_status("prone"):
                    target.add_status("prone")
                self._act_log.add(
                    f"{npc.name}使用扑倒——{target.name}被扑倒在地!")
            else:
                self._act_log.add(
                    f"{npc.name}使用扑倒，{target.name}稳住了身形 (DC12, roll={save_roll})")

        elif "跃起" in name:
            # 跳向 2 格内目标相邻格，用短棒攻击，部位概率: 头40%/躯干60%
            dist = max(abs(nc - tc), abs(nr - tr))
            if dist <= 2:
                # 移动到相邻格
                for _ in range(dist - 1):
                    self._move_npc_toward(npc, nc, nr, tc, tr)
                    npc.ap -= _move_ap_cost(npc, halved=npc.has_status("prone") or npc.has_status("hiding"))
                    pos = self._state.get_entity_pos(npc)
                    if pos: nc, nr = pos
                # 近战攻击（单手短棒），部位概率改变
                weapon_action = {"name": "短棒", "weapon": "短棒", "type": "melee_attack",
                                 "damage": "1d4", "damage_type": "bludgeoning",
                                 "attack_stat": "str", "ap_cost": 20, "reach": 1}
                self._act_log.add(f"{npc.name}跃起砸下短棒!")
                self._npc_melee_attack(npc, weapon_action, target)
            else:
                self._act_log.add(f"{npc.name}跃起——距离太远，够不着")

        elif "格挡" in name:
            # AC+1 直到下回合（用 status 标记）
            if not npc.has_status("guarding"):
                npc.add_status("guarding")
            self._act_log.add(f"{npc.name}举起盾牌格挡，全身 AC+1")

        else:
            self._act_log.add(f"{npc.name} 使用了{name}")

    def _npc_action_total_ap(self, npc: Entity, action: dict,
                              nc: int, nr: int, pc: int, pr: int) -> int | None:
        """计算执行动作所需的总 AP（移动 + 动作本身）。不可行返回 None。"""
        atype = action.get("type", "melee_attack")
        reach = action.get("reach", 1)
        ap_cost = action.get("ap_cost", 30)
        dist = max(abs(nc - pc), abs(nr - pr))

        if atype in ("melee_attack", "special"):
            if dist <= reach:
                return ap_cost
            else:
                # 需要移动：每格 _move_ap_cost
                move_ap = (dist - reach) * _move_ap_cost(npc)
                return move_ap + ap_cost
        return ap_cost

    def _execute_npc_action(self, npc: Entity, action: dict,
                            nc: int, nr: int, pc: int, pr: int) -> None:
        """执行单个 NPC 动作：包围移动 → 进入范围 → 发动攻击。"""
        atype = action.get("type", "melee_attack")
        reach = action.get("reach", 1)
        dist = max(abs(nc - pc), abs(nr - pr))

        # 移动到攻击范围内：目标为玩家周围最近的空格（包围）
        while dist > reach and npc.ap > 0:
            target = self._find_surround_target(nc, nr, pc, pr)
            moved = self._move_npc_toward(npc, nc, nr, target[0], target[1])
            npc.ap -= _move_ap_cost(npc, halved=npc.has_status("prone") or npc.has_status("hiding"))  # 尝试移动即消耗 AP
            if not moved:
                break
            pos = self._state.get_entity_pos(npc)
            if pos:
                nc, nr = pos
                dist = max(abs(nc - pc), abs(nr - pr))
            else:
                break

        # 在范围内则发动攻击
        if atype == "melee_attack" and dist <= reach and npc.ap >= action.get("ap_cost", 20):
            self._npc_melee_attack(npc, action, self._state.player)
        elif atype == "special" and dist <= reach and npc.ap >= action.get("ap_cost", 30):
            self._npc_special_action(npc, action, self._state.player,
                                     nc, nr, pc, pr)

    def _find_surround_target(self, nc: int, nr: int,
                               pc: int, pr: int) -> tuple[int, int]:
        """找到玩家周围最佳包围位置（最近且未被占据的相邻格）。"""
        best = None
        best_dist = 999
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if dc == 0 and dr == 0:
                    continue
                tx, ty = pc + dc, pr + dr
                if not self._state.map.within_bounds(tx, ty):
                    continue
                # 检查是否已被占据
                occupied = False
                for _, (ec, er) in self._state.entities:
                    if (ec, er) == (tx, ty):
                        occupied = True
                        break
                if (tx, ty) == (pc, pr):
                    occupied = True
                if occupied:
                    continue
                d = max(abs(nc - tx), abs(nr - ty))
                if d < best_dist:
                    best_dist = d
                    best = (tx, ty)
        return best or (pc, pr)

    # ── Long Rest ──

