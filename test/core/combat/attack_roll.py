"""攻击结算 —— 攻击检定、单次结算、掩体、空目标、通用近战结算、阵营反应。"""
import random
from core.entity import Entity, Weapon, are_hostile
from core.dice import roll_d20, roll_adv_dice, resolve_adv_auto
from core.combat.attack import hit_check, reduce_tenacity, resolve_attack, miss_message, cover_message, compute_attack_adv
from core.combat.cover import resolve_cover_line, terrain_cover_info
from core.movement import Terrain


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
        p = self._state.player

        # AP 已在 handle_action_input 中扣除（含装填），此处不再重复

        # 无目标（空格子或障碍物）→ 直接结束
        if target is None:
            self._log_empty_target(weapon, target_pos)
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            return

        # 攻击掷骰前：目标能看到攻击者 → 记录临时敌对 + 进战斗
        if not self._state.in_combat and target is not p and self._target_can_see_attacker(target_pos, target) \
           and not are_hostile(target, p):
            if target.faction == "中立" or target.faction == "守序":
                target._attitude[id(p)] = "敌对"
                self._act_log.add(f"{target.name} 被激怒，开始反击!")
            self._start_combat_from_ambush(target)

        attacker_pos = self._state.get_entity_pos(p) or self._state.player_pos
        # 视野外/隐匿优势判定（统一视野 = 相邻一圈∪面前扇形）
        hidden = self._state._is_hidden_to(target, p, attacker_pos)
        dist = max(abs(target_pos[0] - attacker_pos[0]), abs(target_pos[1] - attacker_pos[1]))
        out_of_sight = dist > 1 and not self._state._observer_can_see(target, attacker_pos)
        adv = compute_attack_adv(p, target, weapon,
                                 attacker_pos=attacker_pos,
                                 defender_pos=target_pos,
                                 hidden=hidden, out_of_sight=out_of_sight)
        # 协助攻击优势：本次攻击检定消耗 assisted（与属性检定一致）
        if p.has_status("assisted"):
            p.remove_status("assisted")
        # 玩家优势 → 弹出优势选择面板，等待选择点数
        if self._player_adv_deferred(p, adv, pa):
            return
        roll = resolve_adv_auto(roll_adv_dice(advantage=max(adv, 0),
                                              disadvantage=max(-adv, 0)))
        self._finish_single_attack(roll)


    def _finish_single_attack(self, roll: int) -> None:
        """单次攻击掷骰后结算（掩体检查、装填、战技/特殊面板）。"""
        pa = self._state.pending_attack
        weapon = pa["weapon"]
        target = pa.get("target")
        target_pos = pa.get("target_pos")
        p = self._state.player

        hit, _ = hit_check(p, target, weapon, chosen_roll=roll)
        pa["attack_roll"] = roll
        pa["hit"] = hit
        self._act_log.add(f"{self._pn} 使用{weapon.name}攻击 {target.name}! (roll={roll})")

        # 远程武器掩体检查（命中后、进入战技面板前）
        if hit and weapon.weapon_type == "ranged":
            attacker_pos = self._state.get_entity_pos(p) or self._state.player_pos
            tc, tr = target_pos if target_pos else (0, 0)
            blocked, cover_pos = resolve_cover_line(
                roll, attacker_pos, (tc, tr),
                self._state.map, weapon.weapon_type,
                ground_items=self._state.ground_items,
            )
            if blocked:
                hit = False
                pa["hit"] = False
                pa["blocked_by_cover"] = True
                pa["cover_pos"] = cover_pos
                reduce_tenacity(target, roll)
                if cover_pos:
                    cx, cy = cover_pos
                    terrain = self._state.map[cx, cy]
                    info = terrain_cover_info(terrain)
                    if info:
                        cover_ac, cover_type = info
                        self._act_log.add(
                            f"{cover_message(weapon.damage_type)}! roll={roll} < 掩体AC{cover_ac}, "
                            f"位置({cx},{cy}) {cover_type}")
                    else:
                        self._act_log.add(f"{cover_message(weapon.damage_type)}!")
                else:
                    self._act_log.add(f"{cover_message(weapon.damage_type)}!")

        # 弹药武器攻击后变为未装填
        self._unload_ammo(weapon)

        if hit:
            self._state.combat_phase = "select_maneuver"
        else:
            self._state.combat_phase = "select_special"
            if not pa.get("blocked_by_cover"):
                self._act_log.add(miss_message(self._pn, target.name, weapon.damage_type)
                                  + f" (roll={roll})")
            # 身后1格攻击失手 → 暴露位置（阶段4，D16）
            self._state._hide_attack_expose(p, target)

    def _unload_ammo(self, weapon) -> None:
        """弹药武器攻击后变为未装填。"""
        props = getattr(weapon, 'properties', []) or []
        if "ammo" in props:
            weapon.loaded = False

    def _log_empty_target(self, weapon, target_pos) -> None:
        """空目标日志 — 按武器类型查表。"""
        tc, tr = target_pos if target_pos else (0, 0)
        terrain = self._state.map[tc, tr]
        flavor = EMPTY_TARGET_FLAVOR.get(weapon.weapon_type, EMPTY_TARGET_FLAVOR["melee"])
        key = "wall" if terrain == Terrain.WALL else "empty"
        self._act_log.add(flavor[key].format(weapon=weapon.name))

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
            return  # 攻击自己，不触发态度反应
        if target_pos and not self._target_can_see_attacker(target_pos, target):
            return  # 目标看不到攻击者，不知道谁打的
        from core.entity import are_hostile
        if are_hostile(target, attacker):
            return  # 已敌对 → 不重复激怒
        if target.faction == "中立" or target.faction == "守序":
            target._attitude[id(attacker)] = "敌对"
            self._act_log.add(f"{target.name} 被激怒了! 开始反击")
            if self._state.in_combat:
                if target not in self._state.combat_initiative:
                    self._state.combat_initiative.append(target)

