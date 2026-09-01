"""瞄准与投掷 —— 确认目标、法术目标、点火地表、投掷结算与特效。"""
import json
import os
import random
from domain.game_state import GameState
from domain.entity import Entity, Weapon, are_hostile, adjust_favor
import domain.entity as ent
from domain.movement import Terrain, find_path
from domain.fov import LightLevel, compute_fov
from domain.combat.initiative import roll_initiative
from domain.combat.attack import (hit_check, roll_damage, reduce_tenacity,
    apply_damage_type_modifiers, apply_final_damage, parse_dice, roll_dice, resolve_attack,
    miss_message, cover_message, normalize_damage_type)
from domain.combat.flow import CombatFlow
from domain.map.generation import build_world, build_dungeon
from domain.dice import roll_d20, check_dc, roll_2d6
from domain.ai.engine import BehaviorEngine
from domain.rest import short_rest, long_rest
from infrastructure.loader import DataLoader, _load_dialogues, _load_scene_actions
from infrastructure.save.database import SaveManager
from domain.interact import InteractType, scan_interact_targets
from domain.trade import (load_shop, trade_buy, trade_sell, price_to_text,
    copper_to_currency, shop_gold_text, player_receive,
    resolve_items, load_item)
from domain.item_actions import (get_item_actions, find_placeable_tile,
    place_on_ground, remove_from_inventory as item_remove_from_inventory,
    copy_item_with_count, get_throw_range, get_throw_max_range,
    tile_space_used, MAX_TILE_SPACE)
from domain.loot import _add_to_inventory
from presentation.textual.fov import _update_fov


_THROW_EFFECT_HANDLERS = {
    "heal":       "_throw_effect_heal",
    "restore_mp": "_throw_effect_restore_mp",
    "water":      "_throw_effect_water",
    "break":      "_throw_effect_break",
}


class TargetingMixin:

    def _begin_target_choice(self, candidates, position, resume: str) -> None:
        """同格存在多个目标时，切换到左栏目标选择面板。"""
        pa = self._state.pending_attack
        pa["target_candidates"] = list(candidates)
        pa["target_choice_position"] = position
        pa["target_choice_resume"] = resume
        pa["target_choice_active"] = True
        self._act_log.add(
            f"选择目标 ({position[0]},{position[1]})：输入 :A序号确认，:A0取消"
        )
        self._close_input()
        self.refresh_all()

    def confirm_target_choice(self, cmd: str) -> None:
        """确认同格目标选择，并恢复原本的结算流程。"""
        pa = self._state.pending_attack or {}
        candidates = pa.get("target_candidates", [])
        try:
            index = int(cmd[1:]) - 1
        except (ValueError, IndexError):
            self._act_log.add("无效目标序号")
            return
        if index < 0 or index >= len(candidates):
            self._act_log.add("目标序号无效")
            return
        position = pa.get("target_choice_position")
        current = self._state.get_damageables_at(*position)
        target = candidates[index]
        if target not in current:
            self._act_log.add("目标已不可选，请重新选择")
            self.refresh_all()
            return
        pa.pop("target_candidates", None)
        pa.pop("target_choice_position", None)
        resume = pa.pop("target_choice_resume", "")
        pa.pop("target_choice_active", None)
        if resume == "ranged":
            self._combat_flow._continue_ranged_target(target, position)
        elif resume == "throw":
            pa["target"] = target
            self._resolve_throw()
        elif resume == "spell":
            self._cast_spell(pa["spell"], target, target_pos=position)
        elif resume == "spell_multi":
            pa["targets"].append((position[0], position[1], target))
            if len(pa["targets"]) < pa["target_count"]:
                self._state.combat_phase = "ranged_target"
                self._state.observe_cursor = self._state.controlled_entity_pos
                self.refresh_all()
            else:
                self._cast_spell(
                    pa["spell"], [item[2] for item in pa["targets"]],
                )
        elif resume == "spell_shape":
            pa["shape_targets"].append(target)
            pa["shape_target_index"] += 1
            self._continue_shape_targeting()

    def _continue_shape_targeting(self) -> None:
        """继续收集 target 模式范围形状内的逐格目标。"""
        pa = self._state.pending_attack
        cells = pa["shape_target_cells"]
        while pa["shape_target_index"] < len(cells):
            position = cells[pa["shape_target_index"]]
            candidates = self._state.get_damageables_at(*position)
            if len(candidates) > 1:
                self._begin_target_choice(candidates, position, "spell_shape")
                return
            if candidates:
                pa["shape_targets"].append(candidates[0])
            pa["shape_target_index"] += 1
        pa["affected_cells"] = cells
        self._cast_spell(
            pa["spell"], pa["shape_targets"],
            target_pos=pa.get("target_pos"),
        )

    def cancel_target_choice(self) -> None:
        """取消同格目标选择，回到原瞄准阶段。"""
        pa = self._state.pending_attack or {}
        pa.pop("target_candidates", None)
        pa.pop("target_choice_position", None)
        pa.pop("target_choice_resume", None)
        pa.pop("target_choice_active", None)
        self.refresh_all()

    def _confirm_ranged_target(self) -> None:
        """Enter 键确认远程目标选择。多目标模式依次收集目标，满后统一结算。"""
        if self._state.combat_phase != "ranged_target":
            return
        pa = self._state.pending_attack
        # ── 多目标模式 ──
        if pa.get("target_count", 1) > 1:
            pc, pr = self._state.controlled_entity_pos
            oc, orow = self._state.observe_cursor
            rng = pa.get("max_range", 1)
            if max(abs(oc - pc), abs(orow - pr)) > rng:
                self._act_log.add("目标超出了射程")
                self.refresh_all()
                return
            candidates = self._state.get_damageables_at(oc, orow)
            if len(candidates) > 1:
                self._begin_target_choice(candidates, (oc, orow), "spell_multi")
                return
            target = candidates[0] if candidates else None
            pa["targets"].append((oc, orow, target))
            target_count = pa["target_count"]
            if len(pa["targets"]) < target_count:
                self._state.observe_cursor = self._state.controlled_entity_pos
                spell = pa.get("spell", {})
                self._act_log.add(
                    f"选择 {spell.get('name', '法术')} 目标 "
                    f"({len(pa['targets'])+1}/{target_count})"
                )
                self.refresh_all()
                return
            if pa.get("mode") == "spell":
                spell = pa.get("spell", {})
                self._cast_spell(spell, [t for _, _, t in pa["targets"]])
            return
        # ── 单目标模式 ──
        if pa and pa.get("mode") == "throw":
            candidates = self._state.get_damageables_at(*self._state.observe_cursor)
            if len(candidates) > 1:
                self._begin_target_choice(
                    candidates, self._state.observe_cursor, "throw"
                )
                return
            self._resolve_throw()
            return
        if pa and pa.get("mode") == "spell":
            self._confirm_spell_target()
            return
        if pa and pa.get("mode") == "action":
            self._confirm_action_target(pa)
            return
        if pa and pa.get("mode") == "torch_ignite_surface":
            self._confirm_ignite_surface(pa)
            return
        if pa and pa.get("mode") == "plant":
            self._confirm_plant(pa)
            return
        if pa and pa.get("mode") == "pour_water":
            self._confirm_pour_water(pa)
            return
        if pa and pa.get("mode") == "fetch_water":
            self._confirm_fetch_water(pa)
            return
        if pa and pa.get("mode") == "ignite_surface":
            self._confirm_ignite_surface(pa)
            return
        self._combat_flow.confirm_ranged_target()
        self.refresh_all()

    def _confirm_spell_target(self) -> None:
        """Enter 确认法术瞄准目标：统一选格子，范围允许即可选自身/空地/死亡。"""
        pa = self._state.pending_attack or {}
        spell = pa.get("spell")
        if not spell:
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return
        oc, orow = self._state.observe_cursor
        pc, pr = self._state.controlled_entity_pos
        rng = pa.get("max_range", 1)
        if max(abs(oc - pc), abs(orow - pr)) > rng:
            self._act_log.add("目标超出了射程")
            self.refresh_all()
            return
        from domain.combat.shape import shape_cells, shape_from_pending_attack
        shape = shape_from_pending_attack(pa)
        cells = shape_cells((oc, orow), shape)
        if any(
            not (0 <= col < self._state.map.width and 0 <= row < self._state.map.height)
            or max(abs(col - pc), abs(row - pr)) > rng
            for col, row in cells
        ):
            self._act_log.add("法术影响范围超出射程或地图边界")
            self.refresh_all()
            return
        if not shape.is_single:
            target_mode = spell.get("target_mode")
            if target_mode not in ("target", "area"):
                target_mode = "area" if spell.get("effect", {}).get("area") else "target"
            targets = []
            if target_mode == "target":
                pa["shape_target_cells"] = cells
                pa["shape_target_index"] = 0
                pa["shape_targets"] = targets
                pa["target_pos"] = (oc, orow)
                self._continue_shape_targeting()
                return
            for col, row in cells:
                targets.extend(self._state.get_damageables_at(col, row))
            pa["affected_cells"] = cells
            self._cast_spell(spell, targets, target_pos=(oc, orow))
            return
        candidates = self._state.get_damageables_at(oc, orow)
        if len(candidates) > 1:
            self._begin_target_choice(candidates, (oc, orow), "spell")
            return
        target = candidates[0] if candidates else None
        self._cast_spell(spell, target, target_pos=(oc, orow))

    def _confirm_plant(self, pa: dict) -> None:
        """确认种植位置：相邻格、可播种则消耗种子与 1 钟摆。"""
        from domain.crops import can_plant_at, plant_seed
        from domain.item_actions import remove_from_inventory

        oc, orow = self._state.observe_cursor
        pc, pr = self._state.controlled_entity_pos
        if max(abs(oc - pc), abs(orow - pr)) > 1:
            self._act_log.add("种植只能在相邻格")
            self.refresh_all()
            return
        seed_name = pa.get("seed_name", "")
        pos = (oc, orow)
        if not can_plant_at(self._state, pos, seed_name):
            self._act_log.add("此处无法种植")
            self.refresh_all()
            return
        inv_index = pa.get("seed_inv_index", -1)
        player = self._state.controlled_entity
        item = pa.get("seed_item")
        if item is None or inv_index < 0 or inv_index >= len(player.inventory):
            self._act_log.add("种子已不在背包中")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return
        remove_from_inventory(player, inv_index, 1)
        plant_seed(self._state, pos, seed_name)
        self._state.clock.tick_action(1)
        self._begin_input_interval()
        self._act_log.add(f"在 ({oc},{orow}) 种下了 {seed_name}")
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self.refresh_all()

    def _confirm_pour_water(self, pa: dict) -> None:
        """确认倒水：相邻格变潮湿，水瓶变空玻璃瓶。"""
        from domain.crops import apply_wet_to_tile
        from domain.item_actions import remove_from_inventory

        oc, orow = self._state.observe_cursor
        pc, pr = self._state.controlled_entity_pos
        if max(abs(oc - pc), abs(orow - pr)) > 1:
            self._act_log.add("倒水只能在相邻格")
            self.refresh_all()
            return
        inv_index = pa.get("inv_index", -1)
        player = self._state.controlled_entity
        item = pa.get("item")
        if item is None or item.name != "一瓶水":
            self._act_log.add("水瓶已不在背包中")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return
        if inv_index < 0 or inv_index >= len(player.inventory):
            self._act_log.add("水瓶已不在背包中")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return
        if remove_from_inventory(player, inv_index, 1) is None:
            self._act_log.add("无法倒出水瓶")
            self.refresh_all()
            return
        empty = load_item("空玻璃瓶")
        if empty:
            _add_to_inventory(player, empty)
        apply_wet_to_tile(self._state, (oc, orow))
        if self._state.in_combat:
            player.ap -= max(1, getattr(item, "ap_cost", 1))
        else:
            self._state.clock.tick_action(1)
        self._begin_input_interval()
        self._act_log.add(f"将水倒在了 ({oc},{orow})，地面变得潮湿")
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self.refresh_all()

    def _confirm_fetch_water(self, pa: dict) -> None:
        """确认取水：相邻水域，空玻璃瓶变一瓶水。"""
        from domain.item_actions import remove_from_inventory

        oc, orow = self._state.observe_cursor
        pc, pr = self._state.controlled_entity_pos
        if max(abs(oc - pc), abs(orow - pr)) > 1:
            self._act_log.add("取水只能在相邻格")
            self.refresh_all()
            return
        if self._state.map[oc, orow] != Terrain.WATER:
            self._act_log.add("此处不是水源")
            self.refresh_all()
            return
        inv_index = pa.get("inv_index", -1)
        player = self._state.controlled_entity
        item = pa.get("item")
        if item is None or item.name != "空玻璃瓶":
            self._act_log.add("空玻璃瓶已不在背包中")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return
        if inv_index < 0 or inv_index >= len(player.inventory):
            self._act_log.add("空玻璃瓶已不在背包中")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return
        if remove_from_inventory(player, inv_index, 1) is None:
            self._act_log.add("无法取水")
            self.refresh_all()
            return
        water = load_item("一瓶水")
        if water:
            _add_to_inventory(player, water)
        if self._state.in_combat:
            player.ap -= max(1, getattr(item, "ap_cost", 1))
        else:
            self._state.clock.tick_action(1)
        self._begin_input_interval()
        self._act_log.add(f"{self._pn} 用空玻璃瓶装了满满一瓶水")
        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self.refresh_all()

    def _confirm_ignite_surface(self, pa: dict) -> None:
        """确认点火目标（火把点火地表 / 空玻璃瓶生火）。

        效果彼此独立：
        1. 点燃地表（目标格为 FLAMMABLE 时）
        2. 生物灼烧判定（目标格有生物时，与远程攻击命中一致，仅判定无伤害）
        """
        from domain.grid import FLAMMABLE, FUEL
        from domain.fov import LightLevel
        from domain.combat.attack import roll_hit_location, _apply_burn_effect
        from domain.element import BurningSurface

        pc, pr = self._state.controlled_entity_pos
        oc, orow = self._state.observe_cursor
        # 必须相邻
        if max(abs(oc - pc), abs(orow - pr)) > 1:
            self._act_log.add("只能点燃相邻一格的地表")
            self.refresh_all()
            return

        terrain = self._state.map[oc, orow]
        mode = pa.get("mode", "")
        if mode == "torch_ignite_surface":
            # 火把点火地表 — 消耗 AP
            if self._state.in_combat:
                self._state.controlled_entity.ap -= 10
            self._state.clock.tick_action(1.0)
        elif mode == "ignite_surface":
            # 空玻璃瓶生火 — 不消耗物品，只消耗 AP
            item = pa.get("item")
            if self._state.in_combat:
                self._state.controlled_entity.ap -= item.ap_cost
            self._act_log.add(f"{self._pn} 用 {item.name} 聚焦阳光")

        # 1) 点燃地表（若可燃或为篝火结构——篝火无论是否在烧，点燃即恢复为永久火源）
        if terrain in FLAMMABLE:
            fuel = FUEL.get(terrain, 8)
            self._state.burning_surfaces[(oc, orow)] = BurningSurface(fuel=fuel)
            self._state.register_light((oc, orow), 1, LightLevel.BRIGHT)
        elif any(
            item_pos == (oc, orow) and item.name == "篝火"
            for item, item_pos in self._state.ground_items
        ):
            self._state.burning_surfaces[(oc, orow)] = BurningSurface(fuel=None, tier=3)
            self._state.register_light((oc, orow), 3, LightLevel.BRIGHT)
        else:
            self._act_log.add("这里无法点燃")

        # 2) 生物灼烧判定（独立于地表点燃，不排除玩家自身）
        target_ent = self._state.get_entity_at(oc, orow)
        if target_ent and not target_ent.is_dead:
            location = roll_hit_location(target_ent.body_type)
            _apply_burn_effect(target_ent, location)
            self._act_log.add(f"火焰舔舐了{target_ent.name}的{location}")

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._begin_input_interval()
        _update_fov(self._state)
        self.refresh_all()

    def _is_bright_or_near_light(self) -> bool:
        """检查玩家是否在明亮区域或有强光源在附近（用于空玻璃瓶生火判定）。"""
        pc, pr = self._state.controlled_entity_pos
        # 玩家所在格在明亮视野中
        if (pc, pr) in self._state.fov_bright:
            return True
        # 周围 8 格内有强光源
        for dc in range(-2, 3):
            for dr in range(-2, 3):
                if dc == 0 and dr == 0:
                    continue
                pos = (pc + dc, pr + dr)
                if pos in self._state.light_sources:
                    return True
        return False

    def _bresenham_line(self, x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
        """Bresenham 直线算法，返回从 (x0,y0) 到 (x1,y1) 的所有格子坐标（含两端）。"""
        points = []
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        cx, cy = x0, y0
        while True:
            points.append((cx, cy))
            if (cx, cy) == (x1, y1):
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                cx += sx
            if e2 < dx:
                err += dx
                cy += sy
        return points

    def _find_throw_landing(self, cursor: tuple[int, int], item) -> tuple[int, int]:
        """从目标格开始统一搜索物品可放置的最近空位。"""
        return find_placeable_tile(
            self._state.ground_items,
            cursor[0],
            cursor[1],
            item,
            self._state.map.width,
            self._state.map.height,
            map=self._state.map,
            entities=self._state.entities,
        )

    def _resolve_throw(self) -> None:
        """结算投掷。"""
        pa = self._state.pending_attack
        item = pa["throw_item"]
        inv_index = pa["throw_inv_index"]
        cursor = self._state.observe_cursor
        attacker = self._state.controlled_entity
        pc, pr = self._state.controlled_entity_pos

        # 从背包扣除
        single = item_remove_from_inventory(attacker, inv_index, 1)
        if single is None:
            self._act_log.add("投掷失败：物品数量不足")
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return

        # 查找落点生物（可选自身，无特例）
        if "target" in pa:
            target = pa["target"]
        else:
            candidates = self._state.get_damageables_at(cursor[0], cursor[1])
            target = candidates[0] if candidates else None
        # 投掷 → 破坏隐匿
        self._state._break_stealth_in_view(attacker)

        throw_effect = getattr(single, 'throw_effect', '') or getattr(single, 'effect', '')

        # 哈希表分发投掷特效
        handler_name = _THROW_EFFECT_HANDLERS.get(throw_effect)
        if handler_name:
            getattr(self, handler_name)(single, cursor, target)
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self.refresh_all()
            return

        # 武器投掷：命中检定
        if getattr(single, 'weapon_type', '') or getattr(single, 'damage', ''):
            # 空地：武器落地（沿轨迹回溯合法格）
            if target is None:
                landing = self._find_throw_landing(cursor, single)
                place_on_ground(self._state.ground_items, single, landing[0], landing[1])
                self._state.invalidate_spatial_cache()
                self._act_log.add(f"{self._pn} 投掷了{single.name}")
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
            if not isinstance(target, Entity):
                from domain.damageable import is_destroyed
                dmg = apply_final_damage(target, roll_damage(single, attacker),
                                         single.damage_type)
                if is_destroyed(target):
                    self._state.ground_items = [
                        (item, pos) for item, pos in self._state.ground_items
                        if item is not target
                    ]
                    self._state.invalidate_spatial_cache()
                self._act_log.add(
                    f"{self._pn} 投掷{single.name}击中了{target.name}，造成{dmg}点伤害"
                )
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
            # 有目标：命中检定，超正常射程带劣势
            dist = max(abs(cursor[0] - pc), abs(cursor[1] - pr))
            normal_range = pa.get("throw_range", 3)
            if dist > normal_range:
                roll = roll_d20(disadvantage=1)
            else:
                roll = roll_d20()
            mod = attacker.stat_adjust("str")
            target_ac = target.total_ac("chest")
            if roll == 1 or (roll + mod < target_ac and roll != 20):
                # 未命中：沿轨迹回溯合法落点
                self._act_log.add(f"{self._pn} 投掷{single.name}未命中目标")
                landing = self._find_throw_landing(cursor, single)
                place_on_ground(self._state.ground_items, single, landing[0], landing[1])
                self._state.invalidate_spatial_cache()
            else:
                # 命中
                # 命中后：检查视野 → 变敌对 + 进战斗（与近战/远程攻击逻辑一致）
                if target is not attacker and target and not self._state.in_combat:
                    target_pos = cursor
                    if (target_pos[0] - pc) ** 2 + (target_pos[1] - pr) ** 2 <= getattr(target, 'vision_range', 0) ** 2:
                        if target.faction == "中立" or target.faction == "守序":
                            adjust_favor(target, attacker, "敌对")
                            self._act_log.add(f"{target.name} 被激怒，开始反击!")
                        self._start_combat(target)
                dmg = roll_damage(single, attacker, critical=(roll == 20))
                dmg_type = normalize_damage_type(getattr(single, 'damage_type', 'bludgeoning'))
                from domain.damageable import is_destroyed
                dmg = apply_final_damage(target, dmg, dmg_type, critical=(roll == 20))
                self._act_log.add(f"{self._pn} 投掷{single.name}击中了{target.name}，造成{dmg}点伤害")
                # 武器落在目标所在格（若不合法则回溯）
                target_pos = self._state.get_entity_pos(target)
                if target_pos:
                    landing = self._find_throw_landing(target_pos, single)
                else:
                    landing = self._find_throw_landing(cursor, single)
                place_on_ground(self._state.ground_items, single, landing[0], landing[1])
                self._state.invalidate_spatial_cache()
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self.refresh_all()
                return
        else:
            # 普通物品：沿轨迹回溯合法落点
            landing = self._find_throw_landing(cursor, single)
            place_on_ground(self._state.ground_items, single, landing[0], landing[1])
            self._state.invalidate_spatial_cache()
            self._act_log.add(f"{self._pn} 投掷了{single.name}")

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self.refresh_all()

    # ── 投掷特效分发（哈希表）──

    def _throw_effect_heal(self, item, cursor, target) -> None:
        """治疗药水投掷。"""
        if isinstance(target, Entity) and not target.is_dead:
            amt = getattr(item, 'amount', '')
            try:
                count, sides = parse_dice(amt)
                heal_val = roll_dice(count, sides)
            except (ValueError, TypeError):
                heal_val = int(amt) if amt else 0
            target.hp = min(target.max_hp, target.hp + heal_val)
            self._act_log.add(f"药水瓶摔碎了，清澈的液体撒了一地。{target.name}被治愈了生命（+{heal_val}HP）")
        else:
            self._act_log.add("药水瓶摔碎了，清澈的液体撒了一地。")

    def _throw_effect_restore_mp(self, item, cursor, target) -> None:
        """魔力药水投掷。"""
        if isinstance(target, Entity) and not target.is_dead:
            amt = getattr(item, 'amount', '')
            try:
                mp_val = int(amt)
            except (ValueError, TypeError):
                mp_val = 0
            target.mp = min(target.max_mp, target.mp + mp_val)
            self._act_log.add(f"魔力药水摔碎了，蓝色液体渗入土中。{target.name}恢复了精神（+{mp_val}MP）")
        else:
            self._act_log.add("魔力药水摔碎了，蓝色液体渗入土中。")

    def _throw_effect_water(self, item, cursor, target) -> None:
        """一瓶水投掷：潮湿 + 灭火。"""
        from domain.crops import apply_wet_to_tile
        from domain.element import WET_DURATION
        if target and not target.is_dead:
            target.add_status("潮湿", WET_DURATION)
            self._act_log.add(f"水瓶砸碎了，{target.name}被淋湿了")
        apply_wet_to_tile(self._state, cursor)
        if self._state.is_burning(cursor):
            del self._state.burning_surfaces[cursor]
            self._state.unregister_light(cursor)
            self._act_log.add("水花四溅，火被浇灭了！")
        else:
            self._act_log.add("水瓶砸碎了，水花四溅")

    def _throw_effect_break(self, item, cursor, target) -> None:
        """空玻璃瓶投掷：摔碎。"""
        self._act_log.add("空玻璃瓶砸碎了")

