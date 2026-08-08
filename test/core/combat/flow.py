"""战斗流程状态机 —— 攻击方式选择 → 目标选择 → 命中检定 → 战技/特殊行动。"""

import random
from core.entity import Creature, Weapon
from core.dice import roll_d20
from core.combat.attack import hit_check, roll_damage, reduce_tenacity, apply_damage_type_modifiers, resolve_attack
from core.combat.cover import resolve_cover_line


class CombatFlow:
    """管理玩家攻击流程的五阶段状态机。

    app.py 创建实例并委托调用，只保留 UI 反馈（日志、刷新、开战回调）。
    """

    def __init__(self, state, act_log, left_panel, input_bar, map_view,
                 pn: str, start_combat_cb, refresh_all_cb):
        self._state = state
        self._act_log = act_log
        self._left_panel = left_panel
        self._input_bar = input_bar
        self._map_view = map_view
        self._pn = pn
        self._start_combat_from_ambush = start_combat_cb
        self._refresh_all = refresh_all_cb

    # ── 辅助 ──

    def _focus_input(self) -> None:
        self._input_bar.disabled = False
        self._input_bar.focus()

    def _unfocus_input(self) -> None:
        self._input_bar.disabled = True
        self._map_view.focus()

    def _find_adjacent_targets(self) -> list:
        """返回玩家相邻格的所有存活目标，按距离和 HP 排序。"""
        pc, pr = self._state.player_pos
        targets = []
        for creature, (ec, er) in self._state.entities:
            if creature is not self._state.player and creature.hp > 0 \
               and abs(ec - pc) <= 1 and abs(er - pr) <= 1:
                dist = max(abs(ec - pc), abs(er - pr))
                targets.append((dist, creature.hp, creature))
        targets.sort(key=lambda x: (x[0], x[1]))
        return [c for _, _, c in targets]

    # ── 攻击流程入口 ──

    def start_action_phase(self) -> None:
        """按 A 键 → 进入攻击方式选择阶段。"""
        if self._state.combat_phase != "idle":
            return
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {}
        self._act_log.add("[攻击] 选择武器 — 输入 A序号 确认, A0 取消")
        self._focus_input()
        self._refresh_all()

    # ── 阶段一：选择攻击方式 ──

    def handle_action_input(self, cmd: str) -> None:
        """阶段一：选择攻击方式。按动态 action_map 解析序号。"""
        p = self._state.player
        action_map = self._left_panel._action_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            return

        if num == 0:
            self._state.combat_phase = "idle"
            self._state.pending_attack = {}
            self._unfocus_input()
            self._act_log.add("取消攻击")
            self._refresh_all()
            return

        entry = action_map.get(num)
        if entry is None:
            self._act_log.add(f"无效选项: {cmd}")
            return

        mode, weapon = entry
        hit_bonus = 0
        damage_bonus = 0

        if mode.endswith("_blocked"):
            self._act_log.add(f"{weapon.name} 无法用于攻击")
            return
        if mode == "two_hand":
            hit_bonus = 1
            damage_bonus = 2

        if self._state.in_combat and p.ap < weapon.ap_cost:
            self._act_log.add("AP 不足")
            return

        self._state.pending_attack = {
            "mode": mode, "weapon": weapon,
            "hit_bonus": hit_bonus, "damage_bonus": damage_bonus,
            "attack_roll": None, "target": None,
        }

        # 远程武器 → 进入光标选目标模式
        if weapon.weapon_type == "ranged":
            self._state.combat_phase = "ranged_target"
            self._state.observe_cursor = self._state.player_pos
            self._unfocus_input()
            self._act_log.add(
                f"选择远程目标 — 射程:{weapon.range_max} "
                f"[方向键]移动光标 [Enter]确认 [Esc]取消")
            self._refresh_all()
            return

        # 找相邻目标（近战）
        targets = self._find_adjacent_targets()

        if len(targets) == 0:
            self._act_log.add("近战范围内没有目标")
            if not self._state.in_combat:
                # 探索模式无目标，不进入战斗，直接取消
                self._state.combat_phase = "idle"
                self._state.pending_attack = {}
                self._unfocus_input()
            else:
                self._state.combat_phase = "select_action"
            self._refresh_all()
        elif len(targets) == 1:
            target = targets[0]
            # 探索模式：仅敌对目标进入战斗，非敌对先攻击再根据阵营反应决定
            if not self._state.in_combat and target.faction == "hostile":
                self._start_combat_from_ambush(target)
            self._state.pending_attack["target"] = target
            self.execute_attack_roll()
            self._refresh_all()
        else:
            # 多目标：存在敌对目标时才进入战斗
            if not self._state.in_combat:
                hostile = [t for t in targets if t.faction == "hostile"]
                if hostile:
                    self._start_combat_from_ambush(hostile[0])
            self._state.combat_phase = "select_target"
            self._focus_input()
            self._refresh_all()

    # ── 阶段二：选择目标 ──

    def handle_target_input(self, cmd: str) -> None:
        """阶段二：选择目标。输入 T1~Tn。"""
        if cmd == "T0":
            self._state.combat_phase = "select_action"
            self._focus_input()
            self._act_log.add("取消目标选择")
            self._refresh_all()
            return

        try:
            idx = int(cmd[1:]) - 1
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}, 请输入 T序号")
            return

        targets = self._find_adjacent_targets()

        if 0 <= idx < len(targets):
            self._state.pending_attack["target"] = targets[idx]
            self.execute_attack_roll()
        else:
            self._act_log.add("目标序号无效")
        self._refresh_all()

    # ── 阶段二B：远程光标选目标 ──

    def confirm_ranged_target(self) -> None:
        """确认远程目标选择，进入攻击检定。"""
        pa = self._state.pending_attack
        if pa is None:
            return
        cursor = self._state.observe_cursor
        target = self._state.get_entity_at(cursor[0], cursor[1])
        if target is None or target is self._state.player or target.hp <= 0:
            self._act_log.add("光标位置没有可攻击的目标")
            self._refresh_all()
            return
        # 检查目标是否在射程内
        weapon = pa.get("weapon")
        max_range = weapon.range_max if weapon else 8
        pc, pr = self._state.player_pos
        if max(abs(cursor[0] - pc), abs(cursor[1] - pr)) > max_range:
            self._act_log.add("目标超出了射程")
            self._refresh_all()
            return
        # 目标必须在视野内
        if cursor not in self._state.fov_cache:
            self._act_log.add("无法瞄准不可见的目标")
            self._refresh_all()
            return
        pa["target"] = target
        # 探索模式：仅敌对目标进入战斗
        if not self._state.in_combat and target.faction == "hostile":
            self._start_combat_from_ambush(target)
        self.execute_attack_roll()
        self._refresh_all()

    def cancel_ranged_target(self) -> None:
        """取消远程目标选择，返回攻击方式选择。"""
        self._state.combat_phase = "select_action"
        self._state.pending_attack = {}
        self._focus_input()
        self._act_log.add("取消远程攻击")
        self._refresh_all()

    # ── 阶段三：攻击检定 → 进入战技/特殊行动 ──

    def execute_attack_roll(self) -> None:
        """执行攻击检定，根据命中/未命中进入阶段三。"""
        pa = self._state.pending_attack
        weapon = pa["weapon"]
        target = pa["target"]
        p = self._state.player

        # AP 已在 confirm_ranged_target 中扣除（远程），此处处理近战路径
        if pa.get("_ap_deducted"):
            pass
        elif self._state.in_combat:
            p.ap -= weapon.ap_cost

        hit, roll = hit_check(p, target, weapon)

        pa["attack_roll"] = roll
        pa["hit"] = hit
        self._act_log.add(f"{self._pn} 使用{weapon.name}攻击 {target.name}! (roll={roll})")

        # 远程武器掩体检查（命中后、进入战技面板前）
        if hit and weapon.weapon_type == "ranged":
            attacker_pos = self._find_entity_pos(p)
            target_pos = self._find_entity_pos(target)
            if attacker_pos and target_pos:
                blocked, cover_pos = resolve_cover_line(
                    roll, attacker_pos, target_pos,
                    self._state.map, weapon.weapon_type,
                )
                if blocked:
                    hit = False
                    pa["hit"] = False
                    pa["blocked_by_cover"] = True
                    pa["cover_pos"] = cover_pos
                    reduce_tenacity(target, roll)
                    self._act_log.add("攻击被掩体挡住了!")

        if hit:
            self._state.combat_phase = "select_maneuver"
        else:
            self._state.combat_phase = "select_special"
        self._focus_input()

    # ── 阶段三A：命中后选择战技 ──

    def handle_maneuver_input(self, cmd: str) -> None:
        """阶段三A：命中后选择战技。按 maneuver_map 解析。"""
        pa = self._state.pending_attack
        weapon = pa["weapon"]
        target = pa["target"]
        p = self._state.player
        mmap = self._left_panel._maneuver_map

        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        if num == 0:
            # 直接攻击，正常结算
            pass
        elif num in mmap and mmap[num] is not None:
            m = mmap[num]
            if self._state.in_combat:
                if p.ap < m["ap_extra"]:
                    self._act_log.add("AP 不足")
                    self._refresh_all()
                    return
                p.ap -= m["ap_extra"]
            effect = m["effect"]
            if effect == "damage_bonus":
                bonus = roll_d20() % 4 + 1  # 1d4
                pa["damage_bonus"] = pa.get("damage_bonus", 0) + bonus
                self._act_log.add(f"{m['name']}! 伤害+{bonus}")
            elif effect == "disarm":
                t_roll = roll_d20() + target.stat_adjust("str")
                if t_roll < 12:
                    self._act_log.add(f"缴械成功! {target.name} 的武器被打落")
                else:
                    self._act_log.add(f"{target.name} 握紧了武器")
            elif effect == "knockdown":
                t_roll = roll_d20() + target.stat_adjust("dex")
                if t_roll < 12:
                    if "prone" not in target.statuses:
                        target.statuses.append("prone")
                    self._act_log.add(f"扫腿成功! {target.name} 摔倒在地")
                else:
                    self._act_log.add(f"{target.name} 稳住了身形")
        else:
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        # 结算伤害 — 命中已确认，不再重做命中检定
        roll = pa.get("attack_roll", 0)
        critical = (roll == 20)
        dmg = roll_damage(weapon, p, critical=critical)
        dmg += pa.get("damage_bonus", 0)
        dmg = apply_damage_type_modifiers(dmg, weapon.damage_type, target)
        target.hp = max(0, target.hp - dmg)
        self.check_faction_reaction(target)

        self._act_log.add(f"{self._pn} 砍中了 {target.name}, 造成 {dmg} 点伤害")
        if target.hp <= 0:
            self._act_log.add(f"{target.name} 倒在地上，不再动弹")

        # 探索模式：攻击后目标变为敌对 → 进入战斗
        if not self._state.in_combat and target.faction == "hostile" and target.hp > 0:
            self._start_combat_from_ambush(target)

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._unfocus_input()
        self._refresh_all()

    # ── 阶段三B：未命中后选择特殊行动 ──

    def handle_special_input(self, cmd: str) -> None:
        """阶段三B：未命中后选择特殊行动。输入 A0~A3。"""
        pa = self._state.pending_attack
        target = pa["target"]
        weapon = pa["weapon"]
        p = self._state.player

        smap = self._left_panel._special_map
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        action_key = smap.get(num)
        if action_key is None:
            self._act_log.add(f"无效选项: {cmd}")
            self._refresh_all()
            return

        if action_key == "tenacity":
            self._act_log.add(f"削韧: {target.name} 韧性被削减")
        elif action_key == "reroll":
            if self._state.in_combat and p.ap < 2:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 2
            self._act_log.add("奋力一击! 重掷攻击骰")
            result = self.resolve_melee_attack(p, target, weapon)
            if result["hit"]:
                self.check_faction_reaction(target)
                self._act_log.add(f"命中! 造成 {result['damage']} 点伤害")
            else:
                self._act_log.add("再次未命中...")
        elif action_key == "feint":
            if self._state.in_combat and p.ap < 1:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 1
            self._act_log.add("虚晃一招 — 下次攻击命中+2")
        elif action_key == "taunt":
            if self._state.in_combat and p.ap < 1:
                self._act_log.add("AP 不足")
                self._refresh_all()
                return
            if self._state.in_combat:
                p.ap -= 1
            self._act_log.add(f"{self._pn} 挑衅了 {target.name}")

        # 探索模式：攻击后目标变为敌对 → 进入战斗
        if not self._state.in_combat and target.faction == "hostile" and target.hp > 0:
            self._start_combat_from_ambush(target)

        self._state.combat_phase = "idle"
        self._state.pending_attack = {}
        self._unfocus_input()
        self._refresh_all()

    # ── 通用 ──

    def _find_entity_pos(self, target: Creature) -> tuple[int, int] | None:
        """查找生物在地图上的坐标。"""
        for c, (ec, er) in self._state.entities:
            if c is target:
                return (ec, er)
        return None

    def resolve_melee_attack(self, attacker, target, weapon,
                             hit_bonus=0, damage_bonus=0) -> dict:
        """执行一次攻击检定，返回结果 dict。不修改 AP，不切换回合。"""
        attacker_pos = self._find_entity_pos(attacker)
        target_pos = self._find_entity_pos(target)
        result = resolve_attack(
            attacker, target, weapon,
            attacker_pos=attacker_pos, target_pos=target_pos,
            grid=self._state.map,
        )
        if result["hit"]:
            result["damage"] += damage_bonus
        return result

    def check_faction_reaction(self, target: Creature) -> None:
        """玩家攻击非敌对生物后检查阵营反应。"""
        if target.faction == "hostile":
            return
        if target.faction == "neutral" and not target.hostility_triggered:
            target.hostility_triggered = True
            target.original_faction = "neutral"
            target.faction = "hostile"
            self._act_log.add(f"{target.name} 被激怒了! 开始反击")
            if self._state.in_combat:
                if target not in self._state.combat_initiative:
                    self._state.combat_initiative.append(target)
        elif target.faction == "friendly":
            target.friendly_attack_count += 1
            if target.friendly_attack_count >= 2:
                target.original_faction = "friendly"
                target.faction = "hostile"
                self._act_log.add(f"{target.name} 怒不可遏! 开始反击")
                if self._state.in_combat:
                    if target not in self._state.combat_initiative:
                        self._state.combat_initiative.append(target)
            else:
                self._act_log.add(f"{target.name} 被{self._pn}的攻击吓了一跳，但忍住了")
