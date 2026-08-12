"""钟摆时间系统 —— 移动/行动推进、战斗轮、定时事件、NPC 回调。"""
import pytest
from core.pendulum import PendulumClock


@pytest.fixture
def clock():
    return PendulumClock(scale=10)


class TestPendulum:
    def test_move_tick(self, clock):
        clock.tick_move(1)  # speed=1, acc += ceil(10/1)=10
        assert clock.pendulum_count == 1

    def test_move_triggers_pendulum(self, clock):
        assert clock.pendulum_count == 0
        clock.tick_move(1)
        assert clock.pendulum_count >= 1

    def test_action_cost(self, clock):
        clock.tick_action(2.0)  # acc += 2*10 = 20, drains 2 pendulums
        assert clock.pendulum_count == 2

    def test_timed_events(self, clock):
        events = []
        clock.register_timed_event(3, lambda: events.append("fired"))
        clock.tick_move(1)  # count=1
        clock.tick_move(1)  # count=2
        clock.tick_move(1)  # count=3, should fire
        assert "fired" in events

    def test_combat_round_advances_6_pendulums(self, clock):
        clock.tick_combat_round()
        assert clock.pendulum_count == 6

    def test_callback_called_on_tick(self, clock):
        called = []
        clock.set_npc_advance_callback(lambda d: called.append(d))
        clock.tick_move(1)
        assert called == [1.0]
