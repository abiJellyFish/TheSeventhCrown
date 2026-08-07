"""骰子系统测试 —— D20 骰子池（优势劣势可叠加/抵消）、2d6、DC 检定。

参考: test/docs/方案4.md 规则部分
"""

import pytest
from core.dice import check_dc, roll_2d6, roll_d20


class TestD20:
    """基础 D20 测试"""

    def test_roll_d20_range(self):
        """D20 基础范围 1-20"""
        for _ in range(100):
            result = roll_d20()
            assert 1 <= result <= 20

    def test_roll_d20_is_int(self):
        assert isinstance(roll_d20(), int)


class TestAdvantage:
    """优势：额外多掷骰子，任选结果（取最高）"""

    def test_advantage_adds_extra_die(self):
        """优势=1 时多掷 1 颗（共 2 颗），取最高"""
        for _ in range(50):
            result = roll_d20(advantage=1)
            assert 1 <= result <= 20

    def test_advantage_does_not_change_range(self):
        """优势不改变值域"""
        for _ in range(50):
            assert 1 <= roll_d20(advantage=5) <= 20

    def test_multiple_advantage_stack(self):
        """优势=3 时多掷 3 颗（共 4 颗），取最高。
        用足够多样本验证：优势越多，低值出现概率越低"""
        # 统计大量样本中 <=5 的比例，确认优势越多低值越少
        n = 2000
        for adv, max_low5_ratio in [(0, 0.28), (2, 0.05), (5, 0.005)]:
            low_count = sum(1 for _ in range(n) if roll_d20(advantage=adv) <= 5)
            ratio = low_count / n
            assert ratio <= max_low5_ratio + 0.03, (
                f"adv={adv}: low5 ratio={ratio:.3f} > {max_low5_ratio + 0.03}"
            )


class TestDisadvantage:
    """劣势：移除骰子，最低剩余 1 颗"""

    def test_disadvantage_one_removes_die(self):
        """劣势=1 时移除 1 颗（还剩 1 颗），效果等同于正常 D20"""
        # 单次劣势与普通 D20 行为一致（都只有 1 颗骰子）
        for _ in range(100):
            result = roll_d20(disadvantage=1)
            assert 1 <= result <= 20

    def test_disadvantage_minimum_one_die(self):
        """劣势=5 时骰子数 = max(1+0-5, 1) = 1，不会降到 0"""
        for _ in range(100):
            result = roll_d20(disadvantage=5)
            assert 1 <= result <= 20


class TestAdvantageDisadvantageInteraction:
    """优势劣势并存时先抵消"""

    def test_advantage_disadvantage_cancel(self):
        """优势=1 劣势=1 互相抵消（骰子数 = 1+1-1 = 1）"""
        # 大量统计：概率分布应接近均匀（单颗 D20）
        n = 2000
        low_count = sum(1 for _ in range(n) if roll_d20(advantage=1, disadvantage=1) <= 5)
        ratio = low_count / n
        assert 0.15 <= ratio <= 0.35  # 接近 0.25

    def test_advantage_outweighs_disadvantage(self):
        """优势=3 劣势=1 → 骰子数 = 1+3-1 = 3（仍有优势效果）"""
        n = 1000
        low_count = sum(
            1 for _ in range(n) if roll_d20(advantage=3, disadvantage=1) <= 5
        )
        ratio = low_count / n
        assert ratio <= 0.05  # 3 颗骰子选最高，低值概率极低

    def test_disadvantage_outweighs_advantage(self):
        """优势=1 劣势=3 → 骰子数 = max(1+1-3, 1) = 1（正常 D20）"""
        n = 1000
        low_count = sum(
            1 for _ in range(n) if roll_d20(advantage=1, disadvantage=3) <= 5
        )
        ratio = low_count / n
        assert 0.15 <= ratio <= 0.35


class Test2d6:
    """2d6 正态分布"""

    def test_roll_2d6_range(self):
        for _ in range(200):
            result = roll_2d6()
            assert 2 <= result <= 12

    def test_roll_2d6_distribution(self):
        """2d6 最可能值为 7"""
        n = 5000
        results = [roll_2d6() for _ in range(n)]
        avg = sum(results) / n
        assert 6.5 <= avg <= 7.5  # 期望值 ~7


class TestCheckDC:
    """DC 检定"""

    def test_check_dc_success(self):
        """D20 结果 >= DC 则成功"""
        for _ in range(50):
            success, roll = check_dc(adjust=0, dc=10)
            assert success == (roll >= 10)

    def test_check_dc_with_adjustment(self):
        """调整值影响结果"""
        for _ in range(50):
            success, roll = check_dc(adjust=5, dc=15)
            assert success == (roll + 5 >= 15)

    def test_check_dc_nat1_always_fails(self):
        """方案4: D20=1 必定失败（无论调整值）—— 但 check_dc 不做此判断，
        因为 1 的自动失败规则在命中检定时由 attack.py 处理。
        此处只测试 DC 基本逻辑。"""
        # DC 检定本身不包含 nat1/nat20 特殊规则
        pass

    def test_adjustment_can_make_impossible_dc_possible(self):
        """调整值可以让高 DC 变为可能"""
        successes = 0
        for _ in range(200):
            success, _ = check_dc(adjust=0, dc=25)
            if success:
                successes += 1
        assert successes == 0  # 无调整值时 DC25 不可能

        for _ in range(200):
            success, _ = check_dc(adjust=5, dc=25)
            if success:
                successes += 1
        # 调整值 +5 时，需要骰出 20，概率约 5%
        assert successes > 0
