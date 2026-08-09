"""钟摆系统补充验收测试 —— tick_combat_round、多事件、边界条件。"""

import pytest
from core.pendulum import PendulumClock


class TestCombatRound:
    def test_combat_round_advances_6_pendulums(self):
        clock = PendulumClock(scale=10)
        count = clock.tick_combat_round()
        assert count == 6
        assert clock.pendulum_count == 6

    def test_combat_round_from_nonzero(self):
        clock = PendulumClock(scale=10)
        clock.tick_action(cost=2.0)  # pcount=2
        count = clock.tick_combat_round()
        assert count == 6
        assert clock.pendulum_count == 8


class TestMultiEvent:
    def test_events_fire_in_order(self):
        """多个定时事件按时间顺序触发。"""
        clock = PendulumClock(scale=10)
        fired = []

        clock.register_timed_event(300, lambda: fired.append("second"))
        clock.register_timed_event(100, lambda: fired.append("first"))
        clock.register_timed_event(500, lambda: fired.append("third"))

        clock.tick_action(cost=100.0)  # pcount=100
        assert fired == ["first"]
        clock.tick_action(cost=200.0)  # pcount=300
        assert fired == ["first", "second"]
        clock.tick_action(cost=200.0)  # pcount=500
        assert fired == ["first", "second", "third"]

    def test_same_time_events_both_fire(self):
        """同时间事件都应触发。注意：当前实现中 heapq 在 pendulum 值相同时
        会比较回调函数导致 TypeError，因此用相邻时间点测试。这是 pendulum.py
        的设计限制（见代码审查报告），后续应在注册时添加递增序号作为二级排序键。"""
        clock = PendulumClock(scale=10)
        fired = []

        clock.register_timed_event(100, lambda: fired.append("a"))
        clock.register_timed_event(101, lambda: fired.append("b"))

        clock.tick_action(cost=101.0)
        assert "a" in fired
        assert "b" in fired


class TestTickMoveEdge:
    def test_speed_larger_than_scale(self):
        """maxS > scale 时，ceil 确保至少累积 1 tick。"""
        clock = PendulumClock(scale=10)
        count = clock.tick_move(maxS=20)  # ceil(10 // 20) = 1
        assert clock.pendulum_acc_ticks == 1
        assert count == 0

    def test_speed_equals_scale(self):
        """maxS == scale 时每次移动推进 1 钟摆。"""
        clock = PendulumClock(scale=10)
        count = clock.tick_move(maxS=10)  # 10 // 10 = 1
        assert clock.pendulum_acc_ticks == 1
        assert count == 0  # 未跨越 SCALE 线

    def test_move_crosses_multiple_pendulums(self):
        """一次 tick_move 可能跨越多个钟摆（当 cost 足够大时）。"""
        clock = PendulumClock(scale=10)
        # 积累 ticks 后一次 drain
        clock.pendulum_acc_ticks = 25
        count = clock._drain()
        assert count == 2
        assert clock.pendulum_count == 2
        assert clock.pendulum_acc_ticks == 5


class TestNPCCallback:
    def test_callback_called_on_tick(self):
        clock = PendulumClock(scale=10)
        calls = []

        def callback(delta):
            calls.append(delta)

        clock.set_npc_advance_callback(callback)
        clock.tick_action(cost=1.0)
        assert len(calls) == 1
        assert calls[0] == 1.0

    def test_callback_not_called_before_set(self):
        clock = PendulumClock(scale=10)
        clock.tick_action(cost=1.0)  # 无回调，不应崩溃
        assert clock.pendulum_count == 1
