"""死亡豁免与濒死系统。

规则:
- 生命值从非 0 降至 0 → 不累积濒死受伤
- 生命值已为 0 时再受伤 → 累积濒死受伤
- 死亡豁免: D20 >= 10 成功, 3 成功 = 稳定
- D20=1 → 2 次失败; D20=20 → 恢复 1 HP, 结束濒死
- 濒死受伤 >= 生命上限 → 立即死亡
"""

from core.dice import roll_d20


class DeathSaves:
    """管理单个生物的死亡豁免状态。"""

    def __init__(self):
        self.successes: int = 0
        self.failures: int = 0
        self.death_injury: int = 0   # 濒死受伤累积
        self.max_hp: int = 30        # 由外部设置

    @property
    def is_stable(self) -> bool:
        return self.successes >= 3

    @property
    def is_dead(self) -> bool:
        return self.failures >= 3 or self.death_injury >= self.max_hp

    def take_damage_from_above_zero(self, current_hp: int, damage: int, max_hp: int) -> int:
        """从非 0 HP 受到伤害。HP 降至 0 时不累积濒死受伤。

        Returns:
            实际 HP（最低 0）
        """
        self.max_hp = max_hp
        new_hp = max(0, current_hp - damage)
        # 从非 0 到 0: 不累积濒死受伤
        return new_hp

    def take_damage_at_zero(self, damage: int, max_hp: int) -> None:
        """HP 已为 0 时受到伤害，累积濒死受伤。"""
        self.max_hp = max_hp
        self.death_injury += damage

    def roll_save(self) -> None:
        """进行一次死亡豁免。"""
        roll = roll_d20()
        if roll == 1:
            self.failures += 2
        elif roll == 20:
            self.successes = 3  # 立即稳定
        elif roll >= 10:
            self.successes += 1
        else:
            self.failures += 1
