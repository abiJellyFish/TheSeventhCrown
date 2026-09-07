"""攻击结算 —— 攻击检定、单次结算、掩体、空目标、通用近战结算、阵营反应。"""
import random
from domain.entity import Entity, Weapon, make_hostile
from domain.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from domain.combat.attack import (
    apply_final_damage, hit_check, reduce_tenacity, resolve_attack,
    miss_message, cover_message, compute_attack_adv, roll_damage,
)
from domain.damageable import apply_damage, is_destroyed
from domain.combat.cover import resolve_cover_line, terrain_cover_info
from domain.movement import Terrain


# 空目标日志 — 按武器类型区分
EMPTY_TARGET_FLAVOR = {
    "ranged": {"wall": "箭矢射在了墙上", "empty": "箭矢射空了"},
    "melee":  {"wall": "{weapon}砍在了墙上", "empty": "{weapon}挥空了"},
}


class AttackRollMixin:

    # ── 阶段三：攻击检定 → 进入战技/特殊行动 ──

    def execute_attack_roll(self) -> None:
        """执行攻击检定，根据命中/未命中进入阶段三。

        双持模式委托给 _execute_dual_step() 分步处理。
        玩家优势（adv>0）时先进入 adv_select 阶段等待玩家选择点数。
        """
        pa = self._state.pending_attack
        mode = pa.get("mode", "")

        # 双持模式 → 分步结算
        if mode in ("dual_wield", "dual_attack"):
            self._execute_dual_step()
            return

        weapon = pa["weapon"]
        target = pa.get("target")
        target_pos = pa.get("target_pos")
        p = self._state.controlled_entity

        # AP 已在 handle_action_input 中扣除（含装填），此处不再重复
        p.grant_weapon_exp(weapon.category, 0.01)

        from domain.combat.cover import (
            HEIGHT_WALL, redirect_blocked_shape,
        )
        from domain.combat.shape import shape_cells, shape_from_pending_attack
        from domain.combat.target_phase import SurfaceTarget
        origin = self._state.get_entity_pos(p) or self._state.controlled_entity_pos
        shape = shape_from_pending_attack(pa)
        if pa.get("multi_cells"):
            aimed_cells = pa["multi_cells"]
        elif target_pos is not None:
            layer = target_pos[2] if len(target_pos) > 2 else pa.get("target_z", 0)
            aimed_cells = shape_cells((*target_pos[:2], layer), shape)
        else:
            aimed_cells = []
        if aimed_cells:
            cells, blocker, pos = redirect_blocked_shape(
                self._state, origin, aimed_cells, shape, ignore=(p,),
            )
            if blocker is not None:
                pa["target_pos"] = pos
                if blocker is HEIGHT_WALL:
                    pa["target"] = SurfaceTarget(pos)
                else:
                    pa["target"] = blocker
                target = pa["target"]
                target_pos = pos
                if shape.is_single:
                    pa.pop("multi_cells", None)
                else:
                    pa["multi_cells"] = cells

        # 多格形状攻击：逐格独立结算（不进入战技/特殊面板）
        if pa.get("multi_cells"):
            self._attack_multi_cells(weapon, pa["multi_cells"], p)
            self._end_pending_attack(abandoned=False)
            return

        # 无目标：未明确选空气且该格有地表，则打真实地表。
        if target is None:
            if not pa.get("hit_air") and self._hit_surface(weapon, p, target_pos):
                self._end_pending_attack(abandoned=False)
                return
            self._log_empty_target(weapon, target_pos)
            self._end_pending_attack(abandoned=False)
            return

        if isinstance(target, SurfaceTarget):
            if not self._hit_surface(weapon, p, target.position):
                self._log_empty_target(weapon, target.position)
            self._end_pending_attack(abandoned=False)
            return

        if not isinstance(target, Entity):
            self._hit_object_target(weapon, target, p)
            return

        self._provoke_if_seen(target, p, target_pos)

        attacker_pos = self._state.get_entity_pos(p) or self._state.controlled_entity_pos
        # 视野外/隐匿优势判定（统一视野 = 相邻一圈∪面前扇形）
        hidden = self._state._is_hidden_to(target, p, attacker_pos)
        dist = max(abs(target_pos[0] - attacker_pos[0]), abs(target_pos[1] - attacker_pos[1]))
        out_of_sight = dist > 1 and not self._state._observer_can_see(target, attacker_pos)
        # 目标在轻度遮蔽格 → 远程命中劣势（轻度遮蔽特性，即使目标未隐匿）
        from domain.combat.cover import is_light_cover
        light_cover = is_light_cover(self._state, target_pos)
        adv = compute_attack_adv(p, target, weapon,
                                 attacker_pos=attacker_pos,
                                 defender_pos=target_pos,
                                 hidden=hidden, out_of_sight=out_of_sight,
                                 light_cover=light_cover)
        # 协助攻击优势：本次攻击检定消耗 assisted（与属性检定一致）
        if p.has_status("assisted"):
            p.remove_status("assisted")
        # 玩家优势 → 弹出优势选择面板，等待选择点数
        if self._player_adv_deferred(p, adv, pa):
            return
        roll = resolve_adv_auto(roll_adv_dice(advantage=max(adv, 0),
                                              disadvantage=max(-adv, 0)))
        self._finish_single_attack(roll)


    def _finish_single_attack(self, roll: int, *, skip_cover: bool = False) -> None:
        """单次攻击掷骰后结算（掩体检查、装填、战技/特殊面板）。"""
        pa = self._state.pending_attack
        weapon = pa["weapon"]
        target = pa.get("target")
        target_pos = pa.get("target_pos")
        p = self._state.controlled_entity

        if not isinstance(target, Entity):
            self._hit_object_target(weapon, target, p)
            return

        hit, _ = hit_check(p, target, weapon, chosen_roll=roll)
        pa["attack_roll"] = roll
        pa["hit"] = hit
        self._log(f"{self._pn} 使用{weapon.name}攻击 {target.name}! (roll={roll})")

        # 远程武器掩体：挡住则目标改为阻挡物，再按该目标正常结算。
        if hit and not skip_cover and weapon.weapon_type == "ranged":
            attacker_pos = self._state.get_entity_pos(p) or self._state.controlled_entity_pos
            tc, tr = target_pos[:2] if target_pos else (0, 0)
            blocked, cover_pos = resolve_cover_line(
                roll, attacker_pos, (tc, tr),
                self._state.map, weapon.weapon_type,
                ground_items=self._state.ground_items,
            )
            if blocked and cover_pos:
                from domain.obstacle import obstacle_at
                obstacle = obstacle_at(
                    cover_pos, entities=self._state.entities,
                    ground_items=self._state.ground_items,
                )
                if obstacle is not None:
                    pa["target"] = obstacle
                    pa["target_pos"] = cover_pos
                    pa["cover_pos"] = cover_pos
                    self._finish_single_attack(roll, skip_cover=True)
                    return
            if blocked:
                hit = False
                pa["hit"] = False
                pa["blocked_by_cover"] = True
                pa["cover_pos"] = cover_pos
                self._log(f"{cover_message(weapon.damage_type)}!")

        # 弹药武器攻击后变为未装填
        self._unload_ammo(weapon)

        if hit:
            self._state.combat_phase = "select_maneuver"
        else:
            self._state.combat_phase = "select_special"
            if not pa.get("blocked_by_cover"):
                self._log(miss_message(self._pn, target.name, weapon.damage_type)
                                  + f" (roll={roll})")
            self._state._hide_attack_expose(p, target)

    def _hit_object_target(self, weapon, target, p) -> None:
        """物品目标的正常命中结算：扣耐久。"""
        damage = apply_final_damage(target, roll_damage(weapon, p), weapon.damage_type)
        self._log(
            f"{self._pn} 使用{weapon.name}击中{target.name}，"
            f"造成 {damage} 点伤害（耐久 {target.durability}/{target.max_durability}）"
        )
        if is_destroyed(target):
            self._state.ground_items = [
                (item, pos) for item, pos in self._state.ground_items
                if item is not target
            ]
            self._state.invalidate_spatial_cache()
            self._log(f"{target.name} 被破坏")
        self._unload_ammo(weapon)
        self._end_pending_attack(abandoned=False)

    def _unload_ammo(self, weapon) -> None:
        """弹药武器攻击后变为未装填。"""
        props = getattr(weapon, 'properties', []) or []
        if "ammo" in props:
            weapon.loaded = False

    def _hit_surface(self, weapon, attacker, cell) -> bool:
        """对挡住该格的真实地表扣耐久。高度墙落到阻挡源。"""
        from domain.combat.cover import attack_surface_cell
        mapped = attack_surface_cell(self._state, cell)
        if mapped is None:
            return False
        col, row, layer = mapped
        damage = roll_damage(weapon, attacker)
        self._state.damage_surface((col, row), damage, z=layer)
        self._log(
            f"{self._pn} 使用{weapon.name}击中地表，造成 {damage} 点伤害"
        )
        return True

    def _log_empty_target(self, weapon, target_pos) -> None:
        """空目标日志 — 按武器类型查表。"""
        tc, tr, tz = target_pos if target_pos else (0, 0, self._state.active_z)
        flavor = EMPTY_TARGET_FLAVOR.get(weapon.weapon_type, EMPTY_TARGET_FLAVOR["melee"])
        from domain.obstacle import is_full_obstacle
        candidates = self._state.get_damageables_at(tc, tr, z=tz)
        target = candidates[0] if candidates else None
        key = "wall" if is_full_obstacle(target) else "empty"
        self._log(flavor[key].format(weapon=weapon.name))

    def _attack_multi_cells(self, weapon, cells, p) -> None:
        """多格形状攻击：逐格独立完整结算（命中检定/掩体/伤害），不进入战技面板。
        空格或障碍按单格处理（空目标日志），命中障碍按掩体处理。"""
        attacker_pos = self._state.get_entity_pos(p) or self._state.controlled_entity_pos
        from domain.combat.cover import is_light_cover
        for cell in cells:
            targets = self._state.get_damageables_at(cell[0], cell[1], z=cell[2])
            if not targets:
                if not self._hit_surface(weapon, p, cell):
                    self._log_empty_target(weapon, cell)
                continue
            for target in list(targets):
                if not isinstance(target, Entity):
                    damage = apply_final_damage(
                        target, roll_damage(weapon, p), weapon.damage_type
                    )
                    self._log(f"{self._pn} 使用{weapon.name}击中{target.name}，造成 {damage} 点伤害")
                    if is_destroyed(target):
                        self._state.ground_items = [
                            (item, pos) for item, pos in self._state.ground_items
                            if item is not target
                        ]
                        self._state.invalidate_spatial_cache()
                    continue
                self._provoke_if_seen(target, p, cell)
                hidden = self._state._is_hidden_to(target, p, attacker_pos)
                dist = max(abs(cell[0] - attacker_pos[0]), abs(cell[1] - attacker_pos[1]))
                out_of_sight = dist > 1 and not self._state._observer_can_see(target, attacker_pos)
                light_cover = is_light_cover(self._state, cell)
                result = resolve_attack(p, target, weapon, attacker_pos=attacker_pos,
                                        target_pos=cell, grid=self._state.map,
                                        ground_items=self._state.ground_items,
                                        hidden=hidden, out_of_sight=out_of_sight,
                                        light_cover=light_cover)
                self._unload_ammo(weapon)
                pa = self._state.pending_attack
                pa["target"] = target
                pa["hit_entity"] = True
                if not result["hit"]:
                    from domain.classes import available_abilities
                    from domain.combat.tenacity import settle_attack_tenacity
                    if "削韧" in available_abilities(p):
                        settle_attack_tenacity(
                            p, target, weapon, result["roll"],
                            tenacity_action=True,
                            combat_state=self._state,
                            consume_extra=not pa.get("extra_consumed"),
                            note_combo=False,
                        )
                        pa["extra_consumed"] = True
                struck = result.get("hit_target", target)
                if result["hit"]:
                    self._log(f"{self._pn} 使用{weapon.name}击中 {struck.name}，造成 {result['damage']} 点伤害")
                else:
                    self._log(miss_message(self._pn, struck.name, weapon.damage_type) + f" (roll={result['roll']})")
                    if not result.get("blocked_by_cover"):
                        self._state._hide_attack_expose(p, target)

    # ── 双持分步结算 ──


    # ── 通用 ──

    def resolve_melee_attack(self, attacker, target, weapon,
                             hit_bonus=0, damage_bonus=0) -> dict:
        """执行一次攻击检定，返回结果 dict。不修改 AP，不切换回合。"""
        attacker_pos = self._state.get_entity_pos(attacker)
        target_pos = self._state.get_entity_pos(target)
        hidden = False
        out_of_sight = False
        if attacker_pos and target_pos:
            hidden = self._state._is_hidden_to(target, attacker, attacker_pos)
            dist = max(abs(target_pos[0] - attacker_pos[0]), abs(target_pos[1] - attacker_pos[1]))
            out_of_sight = dist > 1 and not self._state._observer_can_see(target, attacker_pos)
        result = resolve_attack(
            attacker, target, weapon,
            attacker_pos=attacker_pos, target_pos=target_pos,
            grid=self._state.map,
            ground_items=self._state.ground_items,
            hidden=hidden, out_of_sight=out_of_sight,
        )
        # 协助攻击优势：本次攻击检定消耗 assisted
        if attacker.has_status("assisted"):
            attacker.remove_status("assisted")
        if result["hit"]:
            result["damage"] += damage_bonus
        return result

    def check_faction_reaction(self, target: Entity, attacker: Entity,
                                target_pos: tuple = None) -> None:
        """攻击非敌对生物后检查阵营反应。视野外攻击不触发。"""
        if target is attacker:
            return
        if target_pos and not self._target_can_see_attacker(target_pos, target):
            return
        if not make_hostile(target, attacker, self._state.party):
            return
        self._log(f"{target.name} 被激怒了! 开始反击")
        if self._state.in_combat and target not in self._state.combat_initiative:
            from domain.combat.initiative import join_rotation
            join_rotation(self._state, target)

    def _provoke_if_seen(self, target, attacker, target_pos) -> bool:
        """探索中被看见的攻击：统一敌对入口，成功则开战。小队无效。"""
        if self._state.in_combat or target is None or target is attacker:
            return False
        if not self._target_can_see_attacker(target_pos, target):
            return False
        if not make_hostile(target, attacker, self._state.party):
            return False
        self._log(f"{target.name} 被激怒，开始反击!")
        self._request_combat(target)
        return True
