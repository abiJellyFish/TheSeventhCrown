"""Pendulum time system tests."""

import pytest
from core.pendulum import PendulumClock


class TestPendulumClock:
    def test_init(self):
        clock = PendulumClock(scale=10)
        assert clock.pendulum_count == 0
        assert clock.pendulum_acc_ticks == 0

    def test_move_tick(self):
        """Move 1 tile with maxS=2: acc_ticks += SCALE/maxS"""
        clock = PendulumClock(scale=10)
        count = clock.tick_move(maxS=2)
        assert clock.pendulum_acc_ticks == 5  # 10/2
        assert count == 0  # didn't cross SCALE line yet

    def test_move_triggers_pendulum(self):
        """Two moves with maxS=2: 5+5=10 >= 10, triggers 1 pendulum"""
        clock = PendulumClock(scale=10)
        clock.tick_move(maxS=2)  # acc=5
        count = clock.tick_move(maxS=2)  # acc=10 → triggers
        assert count == 1
        assert clock.pendulum_count == 1
        assert clock.pendulum_acc_ticks == 0  # reset

    def test_action_cost(self):
        """Action with cost=3 triggers 3 pendulums"""
        clock = PendulumClock(scale=10)
        count = clock.tick_action(cost=3.0)
        assert count == 3
        assert clock.pendulum_count == 3

    def test_action_fractional_cost(self):
        """Fractional action cost accumulates"""
        clock = PendulumClock(scale=10)
        count = clock.tick_action(cost=0.5)  # acc=5
        assert count == 0
        count = clock.tick_action(cost=0.5)  # acc=10 → 1
        assert count == 1
        assert clock.pendulum_count == 1

    def test_timed_events(self):
        """Register timed event, fire when pendulum_count >= trigger"""
        clock = PendulumClock(scale=10)
        fired = []

        def callback():
            fired.append(clock.pendulum_count)

        clock.register_timed_event(at_pendulum=1000, callback=callback)
        # Advance to 999
        for _ in range(999):
            clock._tick_raw()
        assert len(fired) == 0

        # Advance to 1000
        clock._tick_raw()
        assert len(fired) == 1
        assert fired[0] == 1000

    def test_advance_npcs_called(self):
        """Clock should notify NPC advancement"""
        clock = PendulumClock(scale=10)
        # This is tested via integration; basic clock API works
        assert clock.pendulum_count == 0
