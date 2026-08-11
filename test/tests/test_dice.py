"""骰子系统 —— D20 骰子池（优势劣势可叠加/抵消）、2d6、DC 检定。"""
import pytest
from core.dice import check_dc, roll_2d6, roll_d20


class TestD20:
    def test_roll_d20_range(self):
        for _ in range(100):
            assert 1 <= roll_d20() <= 20

    def test_multiple_advantage_stack(self):
        n = 2000
        for adv, max_low5_ratio in [(0, 0.28), (2, 0.05), (5, 0.005)]:
            low_count = sum(1 for _ in range(n) if roll_d20(advantage=adv) <= 5)
            ratio = low_count / n
            assert ratio <= max_low5_ratio + 0.03

    def test_advantage_disadvantage_cancel(self):
        n = 2000
        low_count = sum(1 for _ in range(n) if roll_d20(advantage=1, disadvantage=1) <= 5)
        assert 0.15 <= low_count / n <= 0.35


class Test2d6:
    def test_roll_2d6_range(self):
        for _ in range(200):
            assert 2 <= roll_2d6() <= 12


class TestCheckDC:
    def test_check_dc_success(self):
        for _ in range(50):
            success, roll = check_dc(adjust=0, dc=10)
            assert success == (roll >= 10)

    def test_check_dc_with_adjustment(self):
        for _ in range(50):
            success, roll = check_dc(adjust=5, dc=15)
            assert success == (roll + 5 >= 15)
