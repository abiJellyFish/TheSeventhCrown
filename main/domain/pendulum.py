"""钟摆时间系统 —— 全局时间推进、定时事件。

核心概念：
- SCALE: 时间精度单位。10 AP = 1 钟摆。
- pendulum_count: 已完成的整数钟摆数
- pendulum_acc_ticks: 当前钟摆内碎片累积

参考: test/docs/速度机制2.md
"""

import heapq
import math
from collections.abc import Callable

AP_PER_PENDULUM = 10


class PendulumClock:
    """钟摆时钟，驱动探索模式时间推进。"""

    def __init__(self, scale: int = 10):
        self.scale = scale
        self.pendulum_count: int = 0
        self.pendulum_acc_ticks: int = 0
        # 定时事件堆: [(触发钟摆数, 回调), ...]
        self._timed_events: list[tuple[int, Callable[[], None]]] = []
        # NPC 结算回调（由 GameState 注册）
        self._on_advance_npcs: Callable[[float], None] | None = None
        # 回调期间禁止嵌套 tick：NPC 起身等会再调 tick_action，叠在休息/等待上
        self._advancing = False

    # ---- 核心推进 ----

    def _tick_raw(self) -> None:
        """推进 1 个钟摆（内部）。"""
        self.pendulum_acc_ticks -= self.scale
        self.pendulum_count += 1
        # 注意：NPC 结算已移至 tick_move/tick_action 中
        # 这里只触发定时事件
        self._fire_events()

    def tick_move(self, maxS: float) -> int:
        """移动路径推进：acc += ceil(SCALE / maxS)。返回本次触发的钟摆数。"""
        if maxS <= 0:
            raise ValueError("movement speed must be positive")
        if self._advancing:
            return 0
        delta_ticks = math.ceil(self.scale / maxS)
        self.pendulum_acc_ticks += delta_ticks
        return self._notify_and_drain(delta_ticks / self.scale)

    def tick_action(self, cost: float) -> int:
        """行动路径推进：acc += cost * SCALE。返回本次触发的钟摆数。"""
        if self._advancing:
            return 0
        self.pendulum_acc_ticks += int(cost * self.scale)
        return self._notify_and_drain(cost)

    def _notify_and_drain(self, npc_delta: float) -> int:
        """通知 NPC 后再 drain。嵌套 tick 在 _advancing 期间直接忽略。"""
        self._advancing = True
        try:
            if self._on_advance_npcs:
                self._on_advance_npcs(npc_delta)
            return self._drain()
        finally:
            self._advancing = False

    def tick_combat_round(self) -> int:
        """战斗一轮结束后推进 6 钟摆。不影响移动累积的 ticks。"""
        count = 0
        for _ in range(6):
            self._tick_raw()
            count += 1
        self.pendulum_acc_ticks = 0  # 战斗钟摆不消耗探索移动累积
        return count

    def _drain(self) -> int:
        """消耗累积的 ticks，每次跨越 SCALE 线推进 1 钟摆。"""
        count = 0
        while self.pendulum_acc_ticks >= self.scale:
            self._tick_raw()
            count += 1
        return count

    # ---- 定时事件 ----

    def register_timed_event(self, at_pendulum: int, callback: Callable[[], None]) -> None:
        """注册一个定时事件，当 pendulum_count >= at_pendulum 时触发。"""
        heapq.heappush(self._timed_events, (at_pendulum, callback))

    def _fire_events(self) -> None:
        """触发所有到期的定时事件。"""
        while self._timed_events and self._timed_events[0][0] <= self.pendulum_count:
            _, cb = heapq.heappop(self._timed_events)
            cb()

    # ---- NPC 推进回调 ----

    def set_npc_advance_callback(self, cb: Callable[[float], None]) -> None:
        self._on_advance_npcs = cb


def spend_ap_or_pendulum(state, actor, ap: int) -> bool:
    """战斗扣 AP，探索按 clock.scale（默认 10AP=1钟摆）推进。不足返回 False。"""
    if ap < 0:
        raise ValueError("AP 不能为负")
    if state.in_combat:
        if actor.ap < ap:
            return False
        actor.ap -= ap
        return True
    state.clock.tick_action(ap / state.clock.scale)
    return True
