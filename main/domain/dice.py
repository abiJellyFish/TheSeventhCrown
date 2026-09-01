"""骰子系统 —— D20 骰子池、2d6、DC 检定。

优势：额外多掷 N 颗骰子，任选一颗作为结果（取最高），多个优势可叠加。
劣势：移除 N 颗骰子（抵消优势多出的骰子），最低剩余 1 颗。**最终总是取最高**。
优势劣势并存时先抵消：骰子数 net = 1 + advantage - disadvantage（不低于 1）。

参考: test/docs/方案4.md 规则部分
"""

import random


def roll_adv_dice(advantage: int = 0, disadvantage: int = 0) -> list[int]:
    """掷 D20 原始骰面列表，不做自动选择（供玩家 UI 面板选择点数）。

    Args:
        advantage: 优势数量（额外多掷的骰子数）
        disadvantage: 劣势数量（抵消的优势骰子数）

    Returns:
        1-20 的掷骰结果列表，长度 = max(1, 1 + advantage - disadvantage)
    """
    dice_count = 1 + advantage - disadvantage
    if dice_count < 1:
        dice_count = 1
    return [random.randint(1, 20) for _ in range(dice_count)]


def resolve_adv_auto(rolls: list[int]) -> int:
    """自动取最高值（NPC / 非交互场景）。"""
    return max(rolls)


def roll_d20(advantage: int = 0, disadvantage: int = 0) -> int:
    """掷 D20，支持优势/劣势叠加与抵消。

    劣势 = 抵消一颗优势多出的骰子（不是取低），最终从剩余骰子中取最高。

    Args:
        advantage: 优势数量（额外多掷的骰子数）
        disadvantage: 劣势数量（移除的骰子数）

    Returns:
        1-20 的掷骰结果（取所有骰子中的最高值）
    """
    return resolve_adv_auto(roll_adv_dice(advantage, disadvantage))


def roll_2d6() -> int:
    """掷 2d6（两个六面骰之和）。

    Returns:
        2-12 的结果
    """
    return random.randint(1, 6) + random.randint(1, 6)


def check_dc(adjust: int, dc: int) -> tuple[bool, int]:
    """DC 检定：D20 + 调整值 vs DC。

    Args:
        adjust: 属性/熟练调整值（可为负数）
        dc: 难度等级

    Returns:
        (是否成功, D20 自然结果)
    """
    roll = random.randint(1, 20)
    total = roll + adjust
    return (total >= dc), roll
