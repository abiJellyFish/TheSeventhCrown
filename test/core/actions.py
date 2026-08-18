"""动作解析与执行 —— 玩家/NPC 通用动作（跳跃/推撞/协助/躲藏/搜索/起身/休息等）。"""
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from core.entity import Entity, Item, are_hostile, is_ally
from core.grid import Grid, BLOCKING_TERRAINS
from core.dice import roll_2d6
from core.movement import Terrain, can_enter, find_path
from core.combat.cover import is_full_cover
from core.ai.components import COMPONENTS
from core.pendulum import PendulumClock
from core.explore import _move_ap_cost


class ActionResolverMixin:

    # ═══════════════════════════════════════════════════
    # 通用动作系统（阶段3：动作面板框架 + 控制组件重构）
    # 动作核心 _do_* 全在 GameState（数据+规则层），UI/NPC 只做入口。
    # ═══════════════════════════════════════════════════

    def _find_action(self, actor, action_key: str) -> dict | None:
        """在实体行动表中按 key 查找动作。"""
        for a in actor.actions:
            if isinstance(a, dict) and a.get("key") == action_key:
                return a
        return None

    def _do_action(self, actor, action_key: str, target=None, target_pos=None) -> str:
        """统一动作入口：校验 AP/钟摆（AP 硬约束）→ 执行 _do_<key> → 扣费。

        返回状态："ok" | "no_action" | "no_ap" | "invalid"。
        """
        action = self._find_action(actor, action_key)
        if action is None:
            return "no_action"
        cost_ap = action.get("cost_ap", 0)
        cost_p = action.get("cost_pendulum", 0)
        # AP 硬约束：战斗内不足则拒绝，绝不先扣后退
        if self.in_combat and actor.ap < cost_ap:
            return "no_ap"
        handler = getattr(self, "_do_" + action_key, None)
        if handler is None:
            return "no_action"
        if not handler(actor, target=target, target_pos=target_pos):
            return "invalid"
        # 发动动作（躲藏/起身/转向除外）→ 破坏隐匿
        if action_key not in ("hide", "face", "stand"):
            self._break_stealth_in_view(actor)
        # 统一扣费
        if self.in_combat:
            actor.ap -= cost_ap
        else:
            self.clock.tick_action(cost_p)
        return "ok"

    def _spend_action(self, actor, action_key: str, action=None) -> None:
        """按动作定义扣费（战斗 AP / 探索钟摆）。供 app 拆分流程（如推撞二选一，
        判定与施加分离）在动作结果阶段调用。action 缺省时通过 _find_action 解析。"""
        if action is None:
            action = self._find_action(actor, action_key)
            if action is None:
                return
        cost_ap = action.get("cost_ap", 0)
        cost_p = action.get("cost_pendulum", 0)
        if self.in_combat:
            actor.ap -= cost_ap
        else:
            self.clock.tick_action(cost_p)

    # ---- 动作骨架实现（完整规则在后续阶段细化）----

    def _do_roll(self, actor, target=None, target_pos=None) -> bool:
        """打滚：进入倒地，扑灭火焰。躲藏后可打滚（清隐匿→倒地）；已倒地只扑火保持倒地。"""
        was_burning = actor.has_status("灼烧")
        actor.remove_status("灼烧")
        # 互斥（阶段7.6）：躲藏后可以倒地——打滚清躲藏再进入倒地
        if actor.has_status("hiding"):
            actor.remove_status("hiding")
            self.hidden_from.pop(id(actor), None)
        # 已倒地：只扑火，保持倒地（不重复加 prone）
        if not actor.has_status("prone"):
            actor.add_status("prone", duration=None)
        if self._npc_log_cb:
            if was_burning:
                self._npc_log_cb(f"{actor.name} 在地上打了个滚，扑灭了火焰")
            else:
                self._npc_log_cb(f"{actor.name} 在地上打了个滚")
        return True

    def _do_disengage(self, actor, target=None, target_pos=None) -> bool:
        """撤离：本回合移动不触发借机攻击。"""
        actor.add_status("disengaged")
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 进入撤离状态")
        return True

    def _do_dodge(self, actor, target=None, target_pos=None) -> bool:
        """回避：可见敌人攻击劣势、敏捷豁免优势。"""
        if actor.has_status("incapacitated") or actor.speed <= 0:
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 无法回避")
            return False
        actor.add_status("dodge")
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 进入回避状态")
        return True

    def _do_hide(self, actor, target=None, target_pos=None) -> bool:
        """躲藏（阶段4.6，阶段7.5 拆分起身）：
        未躲藏 → 敏捷检定定对抗值 hide_dc（满足隐匿条件时优势），清空旧配对，自动发现当前能看见自己的观察者。
        起身为独立动作 `_do_stand`；躲藏动作本身不算状态改变。"""
        from core.dice import roll_d20
        actor_pos = self.get_entity_pos(actor)
        if actor_pos is None:
            return False
        if actor.has_status("hiding"):
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 已经处于躲藏状态")
            return False
        if actor.has_status("prone"):
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 处于倒地状态，无法躲藏")
            return False
        adv = 1 if self._stealth_conditions_met(actor_pos, actor_pos) else 0
        roll = roll_d20(advantage=adv, disadvantage=0) + actor.stat_adjust("dex")
        actor.temp_traits["hide_dc"] = roll
        actor.add_status("hiding")
        # 保留视野外观察者的配对（Q5：躲藏不算状态改变），销毁重新能看见自己的配对
        if id(actor) in self.hidden_from:
            existing = self.hidden_from[id(actor)]
            for obs_id in list(existing):
                obs = next((c for c, _ in self.entities if id(c) == obs_id), None)
                if obs is not None and self._observer_can_see(obs, actor_pos):
                    existing.discard(obs_id)
            if not existing:
                self.hidden_from.pop(id(actor), None)
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 躲藏起来 (对抗值 {roll})")
        # 对当前能看见自己的观察者自动发现（不入隐匿表），逐观察者日志
        for c, (ec, er) in self.entities:
            if c.is_dead or c is actor:
                continue
            if self._observer_can_see(c, actor_pos):
                if self._npc_log_cb:
                    self._npc_log_cb(f"{c.name} 发现了 {actor.name}")
        return True

    def _do_stand(self, actor, target=None, target_pos=None) -> bool:
        """起身（阶段7.5/7.6）：解除倒地 / 躲藏状态。

        计费在动作逻辑内部完成（stand 的 actions.json 消耗为 0）：
        倒地起身 30AP/3钟摆；躲藏起身 20AP/2钟摆；无倒地/躲藏状态 → 拒绝。
        战斗内 AP 不足则拒绝；优先解除倒地（若同时倒地+躲藏）。"""
        prone = actor.has_status("prone")
        hiding = actor.has_status("hiding")
        if not prone and not hiding:
            return False
        cost = 30 if prone else 20
        if self.in_combat and actor.ap < cost:
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} AP 不足，无法起身")
            return False
        if prone:
            actor.remove_status("prone")
            body = "起身"
        else:
            actor.remove_status("hiding")
            self.hidden_from.pop(id(actor), None)
            body = "从躲藏中走出"
        if self.in_combat:
            actor.ap = max(0, actor.ap - cost)
        else:
            # 探索模式：cost 为 AP（tick），1 钟摆 = 10 tick → 除以 10 得钟摆数
            self.clock.tick_action(cost / 10)
        if self._npc_log_cb:
            # 探索模式：cost 为 AP(tick)，1 钟摆 = 10 tick → 日志按实际钟摆数显示
            pendulum = int(cost / 10)
            self._npc_log_cb(f"{actor.name} {body} (消耗 {cost if self.in_combat else pendulum} {'AP' if self.in_combat else '钟摆'})")
        return True

    def _hidden_target_names(self, actor: Entity) -> list[str]:
        """返回 actor 对哪些观察者处于隐匿状态（用于躲藏/面板提示）。"""
        names = []
        for obs_id in self.hidden_from.get(id(actor), set()):
            obs = next((c for c, _ in self.entities if id(c) == obs_id), None)
            if obs is not None and not obs.is_dead:
                names.append(obs.name)
        return names

    def _do_search(self, actor, target=None, target_pos=None) -> bool:
        """探查（阶段4.6/阶段5）：
        ① 对视野内所有对其隐匿的实体重新感知检定；
        ② 对视野内已发现的线索做智力检定（阶段5）：通过显示彩蛋文本，未通过显示"一切正常"。"""
        actor_pos = self.get_entity_pos(actor)
        if actor_pos is None:
            return False
        obs_id = id(actor)
        found_any = False
        for target_id, observers in list(self.hidden_from.items()):
            if obs_id not in observers:
                continue
            tgt = next((c for c, _ in self.entities if id(c) == target_id), None)
            if tgt is None or tgt.is_dead:
                continue
            tgt_pos = self.get_entity_pos(tgt)
            if tgt_pos is None or not self._observer_can_see(actor, tgt_pos):
                continue
            if self._passive_spot(actor, tgt):
                observers.discard(obs_id)
                found_any = True
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 搜出了 {tgt.name}")
        # 线索/可调查对象智力检定（阶段5，D9）
        clue_result = self._investigate_clues(actor)
        found_any = found_any or clue_result
        if self._npc_log_cb and not found_any:
            self._npc_log_cb("你感到周围一切正常")
        return True

    def _investigate_clues(self, actor) -> bool:
        """探查时对视野内线索做智力检定、对陷阱做感知检定。
        陷阱通过→ 发现陷阱，日志"发现了一处埋藏的陷阱。"
        线索通过→ 显示彩蛋文本（一次性），返回 True 抑制"一切正常"；
        未通过→ 不揭示，返回 False，交由 _do_search 输出"你感到周围一切正常"。"""
        result = False
        actor_int = actor.stat_adjust("int")
        actor_wis = actor.stat_adjust("wis")
        # 陷阱探查（感知检定）
        for trap in self.traps:
            if self.spot_memo.get(trap.pos, False) or trap.pos not in self.fov_cache:
                continue
            from core.dice import roll_d20
            roll = roll_d20() + actor_wis
            if roll >= trap.dc:
                self.spot_memo[trap.pos] = True
                trap.discovered = True
                trap.sight_log_fired = True
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 发现了一处埋藏的陷阱。")
                result = True
        # 线索探查（智力检定）
        for clue in list(self.clues):
            if clue.investigated or clue.pos not in self.fov_cache:
                continue
            from core.dice import roll_d20
            roll = roll_d20() + actor_int
            if roll >= clue.dc:
                clue.investigated = True
                if self._npc_log_cb:
                    self._npc_log_cb(clue.egg_text or f"你仔细研究{clue.label}，发现了重要线索")
                result = True
        return result

    def _do_jump(self, actor, target=None, target_pos=None) -> bool:
        """跳跃（阶段7 D19）：距离=(速度等级+力量调整)×2；逐格计费；落点对抗挤格受伤；
        跨障碍 DC10 力量（失败撞障倒地）；落点困难地形 DC10 敏捷（失败失足倒地）；
        倒地/躲藏/失能状态不可跳跃。

        计费在动作逻辑内部完成（jump 的 actions.json 消耗为 0），失败拒绝不扣费、
        部分到达（撞障）按已走格数计费、完整落点按整段距离计费。
        """
        if target_pos is None:
            return False
        if (actor.has_status("prone") or actor.has_status("hiding")
                or actor.has_status("incapacitated")):
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 处于倒地/躲藏/失能状态，无法跳跃")
            return False
        actor_pos = self.get_entity_pos(actor)
        if actor_pos is None:
            return False
        if target_pos == actor_pos:
            return True  # 原地跳跃（免费）
        max_steps = (actor.speed + actor.stat_adjust("str")) * 2
        if max_steps <= 0:
            return False
        dx = target_pos[0] - actor_pos[0]
        dy = target_pos[1] - actor_pos[1]
        if max(abs(dx), abs(dy)) > max_steps:
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 超出跳跃距离")
            return False
        path_length = abs(dx) + abs(dy)
        if self.in_combat and actor.ap < path_length * _move_ap_cost(actor):
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} AP 不足，无法完成跳跃")
            return False
        from core.combat.attack import stat_check
        if not self._jump_execute(actor, actor_pos, target_pos, stat_check, path_length):
            return False
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 跳了出去")
        return True

    def _jump_path(self, actor_pos: tuple[int, int],
                   target_pos: tuple[int, int]) -> list[tuple[int, int]]:
        """跳跃路径（含落点，不含起点），曼哈顿：先 x 后 y 逐格步进。"""
        dx = target_pos[0] - actor_pos[0]
        dy = target_pos[1] - actor_pos[1]
        sx = (1 if dx > 0 else (-1 if dx < 0 else 0))
        sy = (1 if dy > 0 else (-1 if dy < 0 else 0))
        path = []
        cx, cy = actor_pos
        for _ in range(abs(dx)):
            cx += sx
            path.append((cx, cy))
        for _ in range(abs(dy)):
            cy += sy
            path.append((cx, cy))
        return path

    def _jump_charge(self, actor, cells: int) -> None:
        """按跳跃到达格数计费：战斗扣 AP（每格 _move_ap_cost），探索推进钟摆（每格按移动速度）。

        tick_move(maxS) 语义为"每格移动的时间参数"，与 move_player 每格 tick_move(speed)
        保持一致：speed1 跳 N 格 = N 钟摆；必须逐格调用，不能合并为 tick_move(N*speed)
        （ceil 非线性会导致计费偏差）。
        """
        if self.in_combat:
            actor.ap = max(0, actor.ap - cells * _move_ap_cost(actor))
        else:
            for _ in range(cells):
                self.clock.tick_move(max(actor.speed, 1))

    def _jump_execute(self, actor, actor_pos, target_pos, stat_check, dist) -> bool:
        """跳跃落点结算：跨障碍/困难地形检定、落点对抗挤格受伤、移动到位。"""
        from core.movement import Terrain, can_enter
        from core.movement import BLOCKING_TERRAINS, DIFFICULT_TERRAINS
        from core.combat.cover import is_full_cover
        path = self._jump_path(actor_pos, target_pos)
        count = dist
        # 跨中间障碍（起点后、落点前的每一格）
        for i in range(count - 1):
            mid = path[i]
            mt = self.map[mid[0], mid[1]]
            if mt in BLOCKING_TERRAINS or is_full_cover(mt):
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 被障碍挡住，无法跳过")
                return False
            if mt in (Terrain.BUSH, Terrain.STONE, Terrain.LOW_WALL):
                if stat_check(actor, "str") < 10:
                    # 撞向障碍 → 落在此障碍格 + 倒地 + 按已走格数计费
                    self.move_entity(actor, actor_pos[0], actor_pos[1],
                                     mid[0], mid[1])
                    actor.add_status("prone", duration=None)
                    self._jump_charge(actor, i + 1)
                    if self._npc_log_cb:
                        self._npc_log_cb(f"{actor.name} 撞上了障碍，摔倒在地")
                    return True
        # 落点生物对抗（挤格受伤）
        landing = target_pos
        occ = self.get_entity_at(landing[0], landing[1])
        if occ is not None and occ is not actor and not occ.is_dead:
            if stat_check(actor, "str") > stat_check(occ, "str"):
                dest = self._find_push_slot((landing[0], landing[1]), actor_pos)
                if dest is None:
                    if self._npc_log_cb:
                        self._npc_log_cb(f"{actor.name} 无法挤入 {occ.name} 所在的落点")
                    return False
                self.move_entity(occ, landing[0], landing[1], dest[0], dest[1])
                dmg = max(0, actor.stat_adjust("str"))
                occ.take_damage(dmg)
                self.move_entity(actor, actor_pos[0], actor_pos[1],
                                 landing[0], landing[1])
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 挤开了 {occ.name} 并落到落点")
            else:
                # actor 对抗失败：被挤回原格，受伤=目标力量调整值
                dmg = max(0, occ.stat_adjust("str"))
                actor.take_damage(dmg)
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 被 {occ.name} 顶回了原格")
            self._jump_charge(actor, count)
            return True
        # 无障碍无人 → 移动到位 + 落点困难地形检定
        self.move_entity(actor, actor_pos[0], actor_pos[1],
                         landing[0], landing[1])
        lt = self.map[landing[0], landing[1]]
        if lt in DIFFICULT_TERRAINS:
            if stat_check(actor, "dex") < 10:
                actor.add_status("prone", duration=None)
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 落点湿滑，失足倒地")
        self._jump_charge(actor, count)
        return True

    def _find_push_slot(self, landing: tuple[int, int],
                        origin: tuple[int, int]) -> tuple[int, int] | None:
        """为跳跃对抗失败被挤开的实体寻找落点相邻空位（优先背离 origin 方向）。"""
        from core.movement import can_enter
        cands = [(1, 0), (-1, 0), (0, 1), (0, -1),
                 (1, 1), (1, -1), (-1, 1), (-1, -1)]
        same_dir = (landing[0] - origin[0], landing[1] - origin[1])
        if same_dir == (0, 0):
            ordered = cands
        else:
            ordered = [same_dir] + [d for d in cands if d != same_dir]
        for dx, dy in ordered:
            dest = (landing[0] + dx, landing[1] + dy)
            if self.map.within_bounds(dest[0], dest[1]) and \
                    can_enter(dest[0], dest[1], self.map, self.entities,
                              landing[0], landing[1]):
                return dest
        return None

    def _shove_check(self, actor, target, target_pos=None) -> str:
        """推撞判定（D11 / 阶段6）：是否可与目标对抗，返回状态串。

        - 目标需相邻、非自身；体型差 >1 → "too_big"（体型太大，自动失败，不进入对抗）
        - 失能目标 → 直接 "win"（自动成功，无需对抗）
        - 否则力量对抗：发动者力量检定 vs 目标（力量 / 敏捷取高）作防御值；
          必定只在判定阶段掷一次骰（UI 面板选择后不再重判）。
        - 返回 "win"（胜出，需至 _apply_shove 施加效果）/ "fail" / "too_big" / "invalid"
        """
        if target is None or target is actor or target.is_dead:
            return "invalid"
        actor_pos = self.get_entity_pos(actor)
        tgt_pos = self.get_entity_pos(target)
        if actor_pos is None or tgt_pos is None:
            return "invalid"
        if max(abs(tgt_pos[0] - actor_pos[0]),
               abs(tgt_pos[1] - actor_pos[1])) > 1:
            return "invalid"
        # 体型限制：目标体型最多高一级（D11）
        from core.entity import size_rank
        if size_rank(target.size) - size_rank(actor.size) > 1:
            return "too_big"
        # 失能目标自动成功
        if target.has_status("incapacitated"):
            return "win"
        # 力量 vs （力量 / 敏捷取高）对抗，点数更大者胜，相同失败（D11）
        from core.combat.attack import stat_check
        attacker_roll = stat_check(actor, "str")
        defender_roll = max(stat_check(target, "str"), stat_check(target, "dex"))
        return "win" if attacker_roll > defender_roll else "fail"

    def _apply_shove(self, actor, target, target_pos=None, result="prone") -> bool:
        """推撞结果施加（仅判定胜出后调用，不再掷骰）：
        "prone" → 撞倒；"push" → 推开 1 格（方向=发动者→目标方向），目标格不可进入则 fallback 撞倒。"""
        if result == "push":
            actor_pos = self.get_entity_pos(actor)
            tgt_pos = self.get_entity_pos(target)
            if actor_pos is None or tgt_pos is None:
                target.add_status("prone", duration=None)
                return True
            dx = tgt_pos[0] - actor_pos[0]
            dy = tgt_pos[1] - actor_pos[1]
            step_x = 1 if dx > 0 else (-1 if dx < 0 else 0)
            step_y = 1 if dy > 0 else (-1 if dy < 0 else 0)
            if step_x == 0 and step_y == 0:  # 同格（不可能）fallback 朝北推
                step_y = 1
            dest = (tgt_pos[0] + step_x, tgt_pos[1] + step_y)
            from core.movement import can_enter
            if can_enter(dest[0], dest[1], self.map, self.entities,
                         tgt_pos[0], tgt_pos[1]):
                self.move_entity(target, tgt_pos[0], tgt_pos[1], dest[0], dest[1])
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 把 {target.name} 推开了一格")
                return True
            # 推不动 → fallback 撞倒
            target.add_status("prone", duration=None)
            if self._npc_log_cb:
                self._npc_log_cb(f"{target.name} 身后是障碍，{actor.name} 将其撞倒在地")
            return True
        # "prone"
        target.add_status("prone", duration=None)
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 一把将 {target.name} 推倒在地")
        return True

    def _do_shove(self, actor, target=None, target_pos=None,
                  result: str = "prone") -> bool:
        """推撞统一动作入口（NPC / _do_action 直接调用）：判定 + 施加 一体。

        返回 True 表示动作已执行（含对抗失败——失败亦消耗 AP/钟摆）；
        返回 False 表示不可推（invalid / 体型差超限），调用方视为"不合法目标、不扣费"。
        """
        st = self._shove_check(actor, target, target_pos)
        if st == "invalid":
            return False
        if st == "too_big":
            if self._npc_log_cb:
                self._npc_log_cb(f"{target.name} 体型太大，无法被推撞")
            return False
        if st == "fail":
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 推了 {target.name} 一下，但没能撼动对方")
            return True  # 失败也是结果，扣 AP/钟摆
        return self._apply_shove(actor, target, target_pos, result)

    def _do_help(self, actor, target=None, target_pos=None) -> bool:
        """协助（D18 / 阶段6 / 阶段10急救）：
        - 目标需相邻，可为任何实体（自身/尸体除外，不限阵营）
        - 目标濒死 → 急救：DC10 感知检定，成功 → 稳定（HP=1+昏迷，清死亡豁免）
        - 目标倒地 → 扶起（移除 prone）
        - 否则 → 目标下次属性检定获得优势（assisted 状态，一次性消耗）
        """
        if target is None or target is actor or target.is_dead:
            return False
        actor_pos = self.get_entity_pos(actor)
        tgt_pos = self.get_entity_pos(target)
        if actor_pos is None or tgt_pos is None:
            return False
        if max(abs(tgt_pos[0] - actor_pos[0]),
               abs(tgt_pos[1] - actor_pos[1])) > 1:
            return False
        if target.has_status("濒死"):
            # 急救：DC10 感知（医药）检定 → 稳定
            from core.dice import roll_d20
            roll = roll_d20() + actor.stat_adjust("wis")
            if roll >= 10:
                target.hp = 1  # hp setter 自动清濒死/昏迷
                target.add_status("昏迷")
                ds = target.death_saves
                if ds:
                    ds.reset()
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 对 {target.name} 进行急救，目标稳定了")
            else:
                if self._npc_log_cb:
                    self._npc_log_cb(f"{actor.name} 尝试急救 {target.name}，但失败了")
            return True
        if target.has_status("prone"):
            target.remove_status("prone")
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 扶起了 {target.name}")
        else:
            target.add_status("assisted")
            if self._npc_log_cb:
                self._npc_log_cb(f"{actor.name} 协助了 {target.name}（下次检定优势）")
        return True

    def _roll_death_save(self, creature) -> str:
        """濒死生物掷一次死亡豁免。返回 "died" | "stable" | "woke" | "ongoing"。

        规则（D24）：d20≥10 成功、<10 失败；1=两失败、20=恢复1HP脱离濒死；
        3 成功=稳定、3 失败=死亡。
        """
        ds = creature._get_death_saves()
        result = ds.roll_save()
        if result == "crit_success":
            creature.hp = 1  # hp setter 清濒死/昏迷
            if self._npc_log_cb:
                self._npc_log_cb(f"{creature.name} 挺了过来，恢复了意识")
            return "woke"
        if ds.is_dead:
            creature._die()
            if self._npc_log_cb:
                self._npc_log_cb(f"{creature.name} 没能挺住，死了")
            return "died"
        if ds.is_stable:
            # 3 成功 → 稳定（HP=1+昏迷）
            creature.hp = 1
            creature.add_status("昏迷")
            if self._npc_log_cb:
                self._npc_log_cb(f"{creature.name} 稳定下来，陷入昏迷")
            return "stable"
        if self._npc_log_cb:
            if result == "crit_fail":
                self._npc_log_cb(f"{creature.name} 的死亡豁免掷出大失败（{ds.failures}失败/{ds.successes}成功）")
            elif result == "failure":
                self._npc_log_cb(f"{creature.name} 的死亡豁免失败（{ds.failures}失败/{ds.successes}成功）")
            else:
                self._npc_log_cb(f"{creature.name} 的死亡豁免成功（{ds.failures}失败/{ds.successes}成功）")
        return "ongoing"

    # ═══════════════════════════════════════════════════
    # 陷阱与线索（阶段5）
    # ═══════════════════════════════════════════════════


    def _do_rest_short(self, actor, target=None, target_pos=None) -> bool:
        """短休。"""
        if self.in_combat:
            if self._npc_log_cb:
                self._npc_log_cb("战斗中无法短休")
            return False
        from core.rest import short_rest
        pos = self.get_entity_pos(actor)
        r = short_rest(actor, self.clock, self.map, pos)
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 短休 (HP+{r['hp_restored']} MP+{r['mp_restored']})")
        return True

    def _do_rest_long(self, actor, target=None, target_pos=None) -> bool:
        """长休。"""
        if self.in_combat:
            if self._npc_log_cb:
                self._npc_log_cb("战斗中无法长休")
            return False
        from core.rest import long_rest
        pos = self.get_entity_pos(actor)
        r = long_rest(actor, self.clock, self.map, pos)
        if self._npc_log_cb:
            self._npc_log_cb(f"{actor.name} 长休 (HP+{r['hp_restored']} MP+{r['mp_restored']})")
        return True



import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

    

import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")



import json
import os

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def _is_two_handed(item) -> bool:
    props = getattr(item, 'properties', []) or []
    return 'two_handed' in props


def _weapon_ap_display(weapon) -> str:
    """返回武器的 AP 消耗显示字符串，含弹药装填信息。"""
    props = getattr(weapon, 'properties', []) or []
    if "ammo" in props and not getattr(weapon, 'loaded', True):
        return f"装填1+攻击{weapon.weapon.ap_cost}AP (未装填)"
    return f"AP:{weapon.weapon.ap_cost}"


def collect_actions(state) -> list[dict]:
    """收集当前装备状态下的所有可用攻击动作。返回动作列表，每项: {mode, weapon, label}。"""
    p = state.player
    left = p.equipment.get("left_hand")
    right = p.equipment.get("right_hand")
    actions = []

    # 分析手部状态
    def hand(weapon, other_weapon):
        """返回手部信息: kind, weapon, can_attack, is_light, ap"""
        if weapon is None:
            if other_weapon and _is_two_handed(other_weapon):
                return {"kind": "blocked", "weapon": None, "can_attack": False}
            return {"kind": "unarmed", "weapon": None, "can_attack": True,
                    "is_light": True, "ap": 10, "name": "徒手"}
        if weapon.weapon is None:
            return {"kind": "shield", "weapon": weapon, "can_attack": False}
        if _is_two_handed(weapon):
            return {"kind": "two_handed", "weapon": weapon, "can_attack": False}
        props = getattr(weapon, 'properties', []) or []
        return {"kind": "weapon", "weapon": weapon, "can_attack": True,
                "is_light": 'light' in props,
                "ap": weapon.weapon.ap_cost, "name": weapon.name,
                "damage": weapon.damage, "damage_type": weapon.damage_type}

    L = hand(left, right)
    R = hand(right, left)

    # 1) 单手武器
    for side, h in [("left", L), ("right", R)]:
        hand_label = "左手" if side == "left" else "右手"
        if h["kind"] == "weapon":
            w = h["weapon"]
            actions.append({"mode": f"{side}_hand", "weapon": w,
                "label": f"{hand_label}武器  {w.name} {w.damage} {w.damage_type} {_weapon_ap_display(w)}"})
        elif h["kind"] == "shield":
            actions.append({"mode": f"{side}_hand_blocked", "weapon": h["weapon"],
                "label": f"{hand_label}武器  {h['weapon'].name} (不能攻击)"})

    # 2) 徒手
    for side, h in [("left", L), ("right", R)]:
        hand_label = "左手" if side == "left" else "右手"
        if h["kind"] == "unarmed":
            actions.append({"mode": f"unarmed_{side}", "weapon": None,
                "label": f"徒手打击({hand_label})  1+力量 钝击 AP:10"})

    # 3) 双持 — 两手都能攻击且都不是双手武器
    if L["can_attack"] and R["can_attack"]:
        l_light = L["is_light"]
        r_light = R["is_light"]
        l_ap = L["ap"]; r_ap = R["ap"]
        l_name = L["name"]; r_name = R["name"]
        if l_light and r_light:
            ap = max(l_ap, r_ap)
            actions.append({"mode": "dual_wield", "weapon": R.get("weapon") or "unarmed",
                "label": f"双持武器  {l_name}+{r_name} AP:{ap}"})
        else:
            actions.append({"mode": "dual_attack", "weapon": R.get("weapon") or "unarmed",
                "label": f"双持攻击  {l_name}({l_ap}AP)+{r_name}({r_ap}AP)"})

    # 4) 双手武器 — 单条
    for h in [L, R]:
        if h["kind"] == "two_handed":
            w = h["weapon"]
            actions.append({"mode": "two_hand", "weapon": w,
                "label": f"双手并用  {w.name} {_weapon_ap_display(w)}"})
            break

    # 5) 双手并用（两用武器）— 一手武器近战 + 另一手空
    for side, h, other in [("left", L, R), ("right", R, L)]:
        hand_label = "左手" if side == "left" else "右手"
        if h["kind"] == "weapon" and h["weapon"].weapon_type == "melee" \
           and other["kind"] == "unarmed":
            w = h["weapon"]
            actions.append({"mode": f"two_hand_{side}", "weapon": w,
                "label": f"双手并用({hand_label})  {w.name} 命中+1 伤害+2 AP:{w.weapon.ap_cost}"})

    # 6) 远程武器近战
    for h in [L, R]:
        if h["kind"] == "two_handed" and h["weapon"].weapon_type == "ranged" \
           and getattr(h["weapon"], 'melee', None):
            w = h["weapon"]; m = w.melee
            actions.append({"mode": "ranged_melee", "weapon": w,
                "label": f"双手攻击(近战)  {w.name} {m['damage']}+力量 {m['damage_type']} AP:{m['ap_cost']}"})
            break

    # 7) 火把点燃/熄灭 — 检查装备栏中手持的火把
    for side, slot in [("left", "left_hand"), ("right", "right_hand")]:
        hand_label = "左手" if side == "left" else "右手"
        hand_item = p.equipment.get(slot)
        if hand_item is None:
            continue
        ls = hand_item.light
        if not ls:
            continue
        condition = ls.condition
        if condition == "lit":
            actions.append({"mode": "torch_extinguish", "weapon": hand_item,
                "label": f"熄灭火把({hand_label})  AP:10"})
            actions.append({"mode": "torch_ignite_surface", "weapon": hand_item,
                "label": f"点火(相邻格)({hand_label})  AP:10"})
        else:
            actions.append({"mode": "torch_ignite", "weapon": hand_item,
                "label": f"点燃火把({hand_label})  AP:10"})

    return actions


_SPECIAL_ACTIONS_CACHE: list | None = None



def _load_special_actions() -> list:
    """加载特殊行动定义。"""
    global _SPECIAL_ACTIONS_CACHE
    if _SPECIAL_ACTIONS_CACHE is not None:
        return _SPECIAL_ACTIONS_CACHE
    path = os.path.join(_DATA_DIR, "maneuvers.json")
    with open(path, "r", encoding="utf-8") as f:
        _SPECIAL_ACTIONS_CACHE = json.load(f).get("special_actions", [])
    return _SPECIAL_ACTIONS_CACHE
