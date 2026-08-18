"""陷阱与线索 —— 数据类、布置/可见性/触发/发现/智力探查，以及单格移动 AP 成本。"""
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


def _move_ap_cost(actor, halved: bool = False) -> int:
    """单格移动 AP 消耗（1 tick = 1 AP）。halved=True 表示速度减半。
    速度减半 = 每格消耗翻倍：ceil(20/speed)。"""
    s = actor.speed / 2.0 if halved else actor.speed
    return max(1, math.ceil(10 / s))



@dataclass
class Trap:
    """地精陷阱（阶段5）：触发一次后失效，布置时同荒地，未发现不渲染。"""
    pos: tuple[int, int]
    damage: str = "1d4"
    dc: int = 10
    armed: bool = True            # 触发一次后失效
    discovered: bool = False      # 镜像 spot_memo（渲染红 `;` 前置条件）
    sight_log_fired: bool = False # 已触发/已发现陷阱进入视野时的一次性日志



@dataclass
class Clue:
    """线索/可调查对象（阶段5）：始终可见（白 `:`），进视野一次性 sight_log，探查智力检定通过显示彩蛋文本。"""
    pos: tuple[int, int]
    label: str = "线索"
    sight_log: str = ""            # 进视野一次性日志（如"一块风干的骨头。"）
    egg_text: str = ""             # 智力检定通过显示的一次性彩蛋文本
    dc: int = 10                   # 探查智力检定 DC
    sight_log_fired: bool = False  # 视野日志是否已发过（一次性）
    investigated: bool = False     # 彩蛋文本是否已念过（一次性）



class ExploreMixin:

    # ═══════════════════════════════════════════════════
    # 陷阱与线索（阶段5）
    # ═══════════════════════════════════════════════════

    def _add_trap(self, pos, damage="1d4", dc=10) -> None:
        self.traps.append(Trap(pos=tuple(pos), damage=damage, dc=dc))

    def _add_clue(self, pos, label="线索", sight_log="", egg_text="", dc=10) -> None:
        self.clues.append(Clue(pos=tuple(pos), label=label, sight_log=sight_log, egg_text=egg_text, dc=dc))

    def get_trap_at(self, pos: tuple[int, int]) -> Trap | None:
        """返回 pos 处的陷阱（若有）。"""
        for t in self.traps:
            if t.pos == pos:
                return t
        return None

    def get_clue_at(self, pos: tuple[int, int]) -> Clue | None:
        """返回 pos 处的线索（若有）。"""
        for c in self.clues:
            if c.pos == pos:
                return c
        return None

    def _is_spot_discovered(self, pos: tuple[int, int]) -> bool:
        """发现记忆查询（spot_memo 单一事实源）。"""
        return self.spot_memo.get(pos, False)

    def _is_trap_visible(self, pos: tuple[int, int]) -> bool:
        """陷阱渲染条件：已发现 或 已触发（触发后红色 ; 揭示位置）。"""
        t = self.get_trap_at(pos)
        if t is None:
            return False
        return self._is_spot_discovered(pos) or not t.armed

    def _is_clue_visible(self, pos: tuple[int, int]) -> bool:
        """线索渲染条件：线索始终可见（白 `:`），进视野即渲染。发现状态只影响日志文本。"""
        return self.get_clue_at(pos) is not None

    def _check_traps(self, creature, pos: tuple[int, int]) -> None:
        """移动挂点：踩中已布置陷阱 → 1d4 穿刺伤害 + 日志，触发一次后失效。"""
        trap = self.get_trap_at(pos)
        if trap is None or not trap.armed:
            return
        from core.combat.attack import parse_dice, roll_dice
        count, sides = parse_dice(trap.damage)
        dmg = roll_dice(count, sides)
        trap.armed = False
        # 触发即揭示位置
        self.spot_memo[pos] = True
        trap.discovered = True
        if self._npc_log_cb:
            self._npc_log_cb(f"{creature.name} 踩中了地精陷阱，被木刺戳到了小腿")
        creature.take_damage(dmg, "piercing")

    def _maybe_discover_spots(self, observer) -> None:
        """被动发现钩子（视野内一次性，接入 spot_memo）：
        - 陷阱：感知检定，命中则存入 spot_memo 并渲染红 `;`，日志"发现了一处埋藏的陷阱"
        - 已触发/已发现陷阱进视野：一次性日志"一处埋藏的陷阱"
        - 线索：始终可见，进视野仅触发一次性 sight_log（无感知检定）"""
        for trap in self.traps:
            pos = trap.pos
            if pos not in self.fov_cache:
                continue
            if not self.spot_memo.get(pos, False):
                from core.dice import roll_d20
                roll = roll_d20() + observer.stat_adjust("wis")
                if roll >= trap.dc:
                    self.spot_memo[pos] = True
                    trap.discovered = True
                    trap.sight_log_fired = True
                    if self._npc_log_cb:
                        self._npc_log_cb(f"{observer.name} 发现了一处埋藏的陷阱。")
            elif not trap.sight_log_fired:
                trap.sight_log_fired = True
                if self._npc_log_cb:
                    self._npc_log_cb("一处埋藏的陷阱")
        for clue in self.clues:
            if clue.sight_log_fired:
                continue
            if clue.pos not in self.fov_cache:
                continue
            clue.sight_log_fired = True
            if self._npc_log_cb and clue.sight_log:
                self._npc_log_cb(clue.sight_log)

    # ═══════════════════════════════════════════════════
    # 隐匿系统（阶段4：躲藏/遮蔽/探查）
    # ═══════════════════════════════════════════════════

    # 被动感知 DC（D9：暂不写死，常量引用）
    PASSIVE_SPOT_DC = 10

