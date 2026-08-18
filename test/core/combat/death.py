"""死亡豁免与濒死系统。

规则:
- 生命值从非 0 降至 0 → 不累积濒死受伤（进入濒死，开始死亡豁免）
- 生命值已为 0 时再受伤 → 累积濒死受伤 + 失败计数（重击 +2）
- 死亡豁免: D20 >= 10 成功, 3 成功 = 稳定（HP=1+昏迷）
- D20=1 → 2 次失败; D20=20 → 恢复 1 HP, 结束濒死
- 3 次失败 → 死亡; 濒死受伤 >= 生命上限 → 立即死亡
- 恢复 HP / 急救成功 → reset() 清空计数
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

    def reset(self) -> None:
        """清空全部豁免计数（恢复 HP/稳定/急救时调用）。"""
        self.successes = 0
        self.failures = 0
        self.death_injury = 0

    def take_damage_from_above_zero(self, current_hp: int, damage: int, max_hp: int) -> int:
        """从非 0 HP 受到伤害。HP 降至 0 时不累积濒死受伤。

        Returns:
            实际 HP（最低 0）
        """
        self.max_hp = max_hp
        new_hp = max(0, current_hp - damage)
        # 从非 0 到 0: 不累积濒死受伤
        return new_hp

    def take_damage_at_zero(self, damage: int, max_hp: int, critical: bool = False) -> None:
        """HP 已为 0 时受到伤害，累积濒死受伤并计失败（重击 +2）。"""
        self.max_hp = max_hp
        self.death_injury += damage
        self.failures += 2 if critical else 1

    def roll_save(self) -> str:
        """进行一次死亡豁免。返回结果类型：
        "crit_success"（20，恢复 1HP 脱离濒死）| "success" | "failure" | "crit_fail"（1，双失败）。
        """
        roll = roll_d20()
        if roll == 1:
            self.failures += 2
            return "crit_fail"
        elif roll == 20:
            return "crit_success"
        elif roll >= 10:
            self.successes += 1
            return "success"
        else:
            self.failures += 1
            return "failure"
