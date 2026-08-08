"""攻击系统 —— 命中检定、部位命中、伤害结算、伤害类型、自动命中。"""

import json
import os
import random
from core.entity import Creature, Weapon
from core.dice import roll_d20
from core.grid import Grid
from core.movement import Terrain
from core.combat.cover import resolve_cover_line


# ═══════════════════════════════════════════════════
# 数据加载辅助
# ═══════════════════════════════════════════════════

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _load_json(path: str) -> dict:
    """加载 JSON 数据文件，不存在则返回空 dict。"""
    full = os.path.join(_DATA_DIR, path)
    if os.path.exists(full):
        with open(full, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _resolve_attack_stat(attacker: Creature, weapon: Weapon) -> int:
    """解析攻击属性调整值。str_or_dex 取较高者。"""
    stat = weapon.attack_stat
    if stat == "str_or_dex":
        return max(attacker.stat_adjust("str"), attacker.stat_adjust("dex"))
    return attacker.stat_adjust(stat)


# ═══════════════════════════════════════════════════
# 命中检定
# ═══════════════════════════════════════════════════

def hit_check(attacker: Creature, defender: Creature, weapon: Weapon) -> tuple[bool, int]:
    """命中检定：D20 + 调整值 vs 目标 AC。

    Returns:
        (是否命中, D20 自然结果)
    """
    roll = roll_d20()
    if roll == 1:
        return False, roll
    if roll == 20:
        return True, roll  # 必定命中且重击

    mod = _resolve_attack_stat(attacker, weapon)
    total = roll + mod
    ac = defender.total_ac("chest")  # 默认打躯干
    return total >= ac, roll


# ═══════════════════════════════════════════════════
# 部位命中
# ═══════════════════════════════════════════════════

def _load_hit_locations() -> dict[str, list[tuple[str, int]]]:
    """加载部位概率表，优先从 JSON 读取，fallback 到硬编码默认值。"""
    data = _load_json("hit_locations.json")
    if data:
        return {k: [(part, prob) for part, prob in v.items()] for k, v in data.items()}
    return {
        "humanoid": [("chest", 60), ("arms", 15), ("legs", 15), ("head", 10)],
        "beast": [("chest", 60), ("legs", 30), ("head", 10)],
        "undead": [("chest", 60), ("arms", 15), ("legs", 15), ("head", 10)],
    }


HIT_LOCATIONS = _load_hit_locations()


def roll_hit_location(body_type: str) -> str:
    """随机命中部位。"""
    table = HIT_LOCATIONS.get(body_type, HIT_LOCATIONS.get("humanoid", []))
    if not table:
        return "chest"
    roll = random.randint(1, 100)
    cumulative = 0
    for part, prob in table:
        cumulative += prob
        if roll <= cumulative:
            return part
    return table[-1][0]  # fallback


# ═══════════════════════════════════════════════════
# 伤害
# ═══════════════════════════════════════════════════

def parse_dice(dice_str: str) -> tuple[int, int]:
    """解析骰子字符串 "1d8" → (数量, 面数)。"""
    if "d" not in dice_str:
        return (int(dice_str), 1)  # flat damage like "1"
    parts = dice_str.split("d")
    count = int(parts[0]) if parts[0] else 1
    sides = int(parts[1])
    return count, sides


def roll_dice(count: int, sides: int) -> int:
    """掷 dice: NdS。"""
    if sides == 1:
        return count  # flat value
    return sum(random.randint(1, sides) for _ in range(count))


def roll_damage(weapon: Weapon, attacker: Creature, critical: bool = False) -> int:
    """掷武器伤害骰。

    Args:
        weapon: 武器
        attacker: 攻击者
        critical: 是否重击（伤害骰翻倍）
    """
    count, sides = parse_dice(weapon.damage)
    if critical:
        count *= 2
    base = roll_dice(count, sides)

    mod = _resolve_attack_stat(attacker, weapon)
    return base + mod


# ═══════════════════════════════════════════════════
# 伤害类型修正
# ═══════════════════════════════════════════════════

def _load_damage_modifiers() -> dict[str, dict[str, str | None]]:
    """加载伤害修正映射表，优先从 JSON 读取，fallback 到硬编码默认值。"""
    data = _load_json("damage_modifiers.json")
    if data:
        return data
    return {
        "immunities": {"poison_immune": "poison", "sleep_immune": None},
        "resistances": {"piercing_resist": "piercing"},
        "vulnerabilities": {"bludgeoning_vulnerable": "bludgeoning", "radiant_vulnerable": "radiant"},
    }


_DAMAGE_MODIFIERS = _load_damage_modifiers()
TRAIT_TO_IMMUNITY = _DAMAGE_MODIFIERS.get("immunities", {})
TRAIT_TO_RESISTANCE = _DAMAGE_MODIFIERS.get("resistances", {})
TRAIT_TO_VULNERABILITY = _DAMAGE_MODIFIERS.get("vulnerabilities", {})


def apply_damage_type_modifiers(damage: int, damage_type: str,
                                defender: Creature) -> int:
    """应用抗性/易伤/免疫。

    结算顺序: 免疫 → 抗性(÷2) → 易伤(×2)
    """
    for trait in defender.traits:
        if TRAIT_TO_IMMUNITY.get(trait) == damage_type:
            return 0
        if TRAIT_TO_RESISTANCE.get(trait) == damage_type:
            damage = damage // 2
        if TRAIT_TO_VULNERABILITY.get(trait) == damage_type:
            damage = damage * 2
    return damage


# ═══════════════════════════════════════════════════
# 完整攻击结算
# ═══════════════════════════════════════════════════

def resolve_attack(
    attacker: Creature, defender: Creature, weapon: Weapon,
    attacker_pos: tuple[int, int] | None = None,
    target_pos: tuple[int, int] | None = None,
    grid: Grid[Terrain] | None = None,
) -> dict:
    """完整一次攻击结算（含掩体检查）。

    Args:
        attacker: 攻击者
        defender: 防御者
        weapon: 武器
        attacker_pos: 攻击者坐标（掩体检查用，可选）
        target_pos: 目标坐标（掩体检查用，可选）
        grid: 地形网格（掩体检查用，可选）

    Returns:
        {
            "hit": bool,
            "critical": bool,
            "roll": int,
            "location": str | None,
            "damage": int,
            "halved": bool,
            "blocked_by_cover": bool,
            "cover_pos": tuple | None,
        }
    """
    hit, roll = hit_check(attacker, defender, weapon)
    if not hit:
        # 未命中 → 削韧
        reduce_tenacity(defender, roll)
        return {"hit": False, "critical": False, "roll": roll,
                "location": None, "damage": 0, "halved": False,
                "blocked_by_cover": False, "cover_pos": None}

    # 掩体检查（仅远程武器，需要坐标和地形网格）
    if weapon.weapon_type == "ranged" and attacker_pos and target_pos and grid:
        blocked, cover_pos = resolve_cover_line(
            roll, attacker_pos, target_pos, grid, weapon.weapon_type
        )
        if blocked:
            reduce_tenacity(defender, roll)  # 掩体阻挡，等效未命中
            return {"hit": False, "critical": False, "roll": roll,
                    "location": None, "damage": 0, "halved": False,
                    "blocked_by_cover": True, "cover_pos": cover_pos}

    critical = (roll == 20)
    location = roll_hit_location(defender.body_type)
    damage = roll_damage(weapon, attacker, critical=critical)

    # 伤害减半判定：命中值 <= 部位 AC × 1.5 则减半
    # （重击不跳过此判定）
    loc_ac = defender.total_ac(location)
    mod = _resolve_attack_stat(attacker, weapon)
    total_hit = roll + mod
    halved = total_hit <= loc_ac * 1.5
    if halved:
        damage = max(1, damage // 2)

    # 伤害类型修正
    damage = apply_damage_type_modifiers(damage, weapon.damage_type, defender)

    # 应用伤害
    defender.hp = max(0, defender.hp - damage)

    return {"hit": True, "critical": critical, "roll": roll,
            "location": location, "damage": damage, "halved": halved,
            "blocked_by_cover": False, "cover_pos": None}


# ═══════════════════════════════════════════════════
# 削韧
# ═══════════════════════════════════════════════════

def reduce_tenacity(target: Creature, d20_roll: int) -> None:
    """未命中时削减目标韧性。公式: max(roll // 5, 1)。
    韧性归零 → 陷入 incapacitated 状态。
    韧性最低为 0。
    """
    reduction = max(d20_roll // 5, 1)
    target.tenacity = max(0, target.tenacity - reduction)
    if target.tenacity == 0 and "incapacitated" not in target.statuses:
        target.statuses.append("incapacitated")


# ═══════════════════════════════════════════════════
# 自动命中攻击（如魔法飞弹）
# ═══════════════════════════════════════════════════

class AutoHitAttack:
    """无需命中检定的攻击（如魔法飞弹）。"""

    def __init__(self, damage_dice: str, missiles: int, damage_type: str):
        self.damage_dice = damage_dice
        self.missiles = missiles
        self.damage_type = damage_type

    def resolve(self, defender: Creature | None) -> list[int]:
        """结算自动命中伤害。返回每发导弹的伤害列表。"""
        count, sides = parse_dice(self.damage_dice)
        results = []
        for _ in range(self.missiles):
            dmg = roll_dice(count, sides)
            if defender:
                dmg = apply_damage_type_modifiers(dmg, self.damage_type, defender)
            results.append(dmg)
        if defender:
            total = sum(results)
            defender.hp = max(0, defender.hp - total)
        return results
