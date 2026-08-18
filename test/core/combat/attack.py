"""攻击系统 —— 命中检定、部位命中、伤害结算、伤害类型、自动命中。"""

import json
import os
import random
from core.entity import Entity, Item, normalize_damage_type
from core.dice import roll_adv_dice, resolve_adv_auto
from core.grid import Grid
from core.movement import Terrain
from core.combat.cover import resolve_cover_line


# ═══════════════════════════════════════════════════
# 优势/劣势掷骰（通用骰子层，见 core/dice.py）
# ═══════════════════════════════════════════════════

def _roll_auto(adv: int) -> int:
    """按整数 adv 自动取高（NPC / 非交互 / 劣势场景）。

    adv > 0（优势）：多掷 adv 颗，取最高，共 1+adv 颗。
    adv < 0（劣势）：抵消掉 |adv| 颗优势骰子，最低 1 颗，取最高。
    adv == 0：单掷。
    """
    advantage = adv if adv > 0 else 0
    disadvantage = -adv if adv < 0 else 0
    return resolve_adv_auto(roll_adv_dice(advantage, disadvantage))


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


def _resolve_attack_stat(attacker: Entity, weapon: Item) -> int:
    """解析攻击属性调整值。str_or_dex 取较高者。"""
    stat = weapon.attack_stat
    if stat == "str_or_dex":
        return max(attacker.stat_adjust("str"), attacker.stat_adjust("dex"))
    return attacker.stat_adjust(stat)


# ═══════════════════════════════════════════════════
# 挥空 / 掩体阻挡 描述表
# ═══════════════════════════════════════════════════

MISS_FLAVOR = {
    "slashing":    "{attacker} 挥动武器，剑刃从{target}身侧掠过",
    "bludgeoning": "{attacker} 的重击砸在了地面上，{target}闪身避开",
    "piercing":    "{attacker} 的刺击被{target}侧身躲过",
    "force":       "{attacker} 的魔力飞弹偏离了{target}",
    "fire":        "{attacker} 的火焰从{target}身旁擦过",
    "cold":        "{attacker} 的寒霜未能触及{target}",
    "lightning":   "{attacker} 的电光被{target}闪开",
    "acid":        "{attacker} 的酸液溅落在{target}脚边",
    "necrotic":    "{attacker} 的暗蚀能量被{target}避开",
    "radiant":     "{attacker} 的光辉未能命中{target}",
    "thunder":     "{attacker} 的音波冲击从{target}身旁掠过",
    "poison":      "{attacker} 的毒雾被{target}躲开",
    "psychic":     "{attacker} 的心灵冲击未能锁定{target}",
    "_default":    "{attacker} 的攻击被{target}躲开了",
}

COVER_FLAVOR = {
    "slashing":    "剑刃砍在了掩体上，火花四溅",
    "bludgeoning": "重击砸在掩体上，发出沉闷的响声",
    "piercing":    "箭矢钉入了掩体",
    "_default":    "攻击被掩体挡住了",
}


def miss_message(attacker_name: str, target_name: str, damage_type: str) -> str:
    """根据伤害类型返回挥空描述。"""
    template = MISS_FLAVOR.get(damage_type, MISS_FLAVOR["_default"])
    return template.format(attacker=attacker_name, target=target_name)


def cover_message(damage_type: str) -> str:
    """根据伤害类型返回掩体阻挡描述。"""
    return COVER_FLAVOR.get(damage_type, COVER_FLAVOR["_default"])


# ═══════════════════════════════════════════════════
# 命中检定
# ═══════════════════════════════════════════════════

def hit_check(attacker: Entity, defender: Entity, weapon: Item | None = None,
              adv: int = 0, chosen_roll: int | None = None,
              guaranteed: bool = False, mod: int | None = None) -> tuple[bool, int]:
    """命中检定：D20 + 调整值 vs 目标 AC。

    Args:
        attacker: 攻击者
        defender: 防御者
        weapon: 武器（用于解析攻击调整值；传 mod 时可为 None）
        adv: 优势/劣势（正=优势，负=劣势，见 _roll_auto）
        chosen_roll: 玩家已选择的骰面（优势面板选择）。非 None 时直接使用，
            跳过自动掷骰。
        guaranteed: 必定命中。检定未通过（含天然1）时，将骰面改为刚好成功的点数
            `max(2, AC - 调整)`（上限 20），必定命中；天然 20 仍为重击。
        mod: 攻击调整值。缺省时用武器解析（weapon.attack_stat）。

    Returns:
        (是否命中, D20 自然结果)
    """
    roll = chosen_roll if chosen_roll is not None else _roll_auto(adv)
    if mod is None:
        mod = _resolve_attack_stat(attacker, weapon)
    ac = defender.total_ac("chest")  # 默认打躯干
    if roll == 20:
        return True, roll  # 天然20必定命中且重击
    if roll == 1 and not guaranteed:
        return False, roll  # 天然1必定未命中
    if roll + mod >= ac:
        return True, roll
    if guaranteed:
        # 必定命中：未通过 → 改为刚好成功的点数（最低非天然1的成功骰面）
        roll = min(20, max(2, ac - mod))
        return True, roll
    return False, roll


def compute_attack_adv(attacker: Entity, defender: Entity, weapon: Item,
                       attacker_pos: tuple[int, int] | None = None,
                       defender_pos: tuple[int, int] | None = None,
                       *,
                       hidden: bool = False,
                       out_of_sight: bool = False) -> int:
    """汇总攻击检定优势/劣势来源，返回 adv 整数（正=优势，负=劣势）。

    阶段1规则（D12 倒地）：
    - 攻击者倒地 → 攻击劣势（-1）
    - 目标倒地：相邻近战 → 优势（+1）；远程或范围外 → 劣势（-1）
    阶段4规则（D16 身后/隐匿/视野外）：
    - 攻击者在目标视野外（含身后>1格）→ 优势（+1，out_of_sight 由调用方判定）
    - 攻击者对目标隐匿 → 优势（+1，hidden 由调用方判定）
    - 攻击者被协助 → 优势（+1，命中后消耗 assisted）
    每个来源独立结算（各 +1 骰子，可叠加）。

    Args:
        hidden: 攻击者对目标成功隐匿（由调用方经 state._is_hidden_to 判定）。
        out_of_sight: 攻击者在目标视野外（相邻一圈 ∪ 面前扇形之外，由调用方判定）。
    """
    adv = 0
    if attacker.has_status("prone"):
        adv -= 1
    if defender.has_status("dodge"):
        # 回避劣势仅对回避者可见的敌人有效（攻击者不在身后扇区）
        if attacker_pos is not None and defender_pos is not None:
            from core.movement import sector_of
            facing = getattr(defender, 'facing', (0, 1))
            delta = (attacker_pos[0] - defender_pos[0],
                     attacker_pos[1] - defender_pos[1])
            if sector_of(facing, delta) != "back":
                adv -= 1
        else:
            adv -= 1                # 无坐标时默认可见
    if defender.has_status("prone"):
        adjacent = False
        if attacker_pos is not None and defender_pos is not None:
            dist = max(abs(attacker_pos[0] - defender_pos[0]),
                       abs(attacker_pos[1] - defender_pos[1]))
            adjacent = dist <= 1
        if weapon.weapon_type == "ranged":
            adv -= 1                    # 远程劣势
        elif adjacent:
            adv += 1                    # 相邻近战优势
        else:
            adv -= 1                    # 范围外劣势
    # 视野外攻击优势（攻击者不在目标相邻一圈∪面前扇形内，含身后>1格）
    if out_of_sight:
        adv += 1
    # 隐匿攻击优势（攻击者对目标成功隐匿）
    if hidden:
        adv += 1
    # 协助攻击优势（被协助 → 本次攻击优势，命中后由调用方消耗）
    if attacker.has_status("assisted"):
        adv += 1
    return adv


def stat_check(creature: Entity, stat: str, adv: int = 0,
               chosen_roll: int | None = None) -> int:
    """属性检定：D20 + 属性调整值，支持优势/劣势。
    若生物有 "assisted"（被协助）状态，本次检定 +1 优势并消耗该状态（D18）。

    Args:
        creature: 进行检定的生物
        stat: 属性名（"str"/"dex"/...）
        adv: 优势/劣势（正=优势，负=劣势，见 _roll_auto）
        chosen_roll: 玩家已选择的骰面（优势面板选择）。非 None 时直接使用。
    """
    # 被协助 → 下次检定优势，消耗之（D18）
    if creature.has_status("assisted"):
        adv += 1
        creature.remove_status("assisted")
    roll = chosen_roll if chosen_roll is not None else _roll_auto(adv)
    return roll + creature.stat_adjust(stat)


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


def roll_damage(weapon: Item, attacker: Entity, critical: bool = False) -> int:
    """掷武器伤害骰（含属性伤害）。

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
    total = base + mod

    # 属性伤害（如火把点燃后的火焰伤害）
    sd = getattr(weapon, 'special_damage', None)
    if sd and _check_special_condition(weapon, sd):
        sd_count, sd_sides = parse_dice(sd.get("amount", "1d4"))
        if critical:
            sd_count *= 2
        total += roll_dice(sd_count, sd_sides)

    return total


# ═══════════════════════════════════════════════════
# 属性伤害效果分发
# ═══════════════════════════════════════════════════

def _check_special_condition(weapon: Item, sd: dict) -> bool:
    """检查属性伤害条件是否满足。"""
    condition = sd.get("condition", "")
    if condition == "always":
        return True
    if condition == "lit":
        light_lit = weapon.light
        return light_lit is not None and light_lit.condition == "lit"
    return False


def _apply_burn_effect(defender: Entity, location: str) -> None:
    """灼烧效果：部位有护甲不燃烧，无护甲 50% 概率附加灼烧。"""
    if defender.has_status("灼烧"):
        return
    armor_map = {"chest": "ac_chest", "arms": "ac_arms",
                 "legs": "ac_legs", "head": "ac_head"}
    armor_slot = armor_map.get(location, "ac_chest")
    if getattr(defender, armor_slot, 0) <= 0 and random.random() < 0.5:
        defender.add_status("灼烧", duration=3)


_SPECIAL_DAMAGE_EFFECTS = {
    "fire": _apply_burn_effect,
    # "cold": _apply_chill_effect,   # 未来扩展
}


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
                                defender: Entity) -> int:
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

    # 潮湿状态：火焰抗性 -2，闪电易伤 ×1.5
    if defender.has_status("潮湿"):
        if damage_type == "fire":
            damage = max(0, damage - 2)
        elif damage_type == "lightning":
            damage = int(damage * 1.5)
    return damage


# ═══════════════════════════════════════════════════
# 完整攻击结算
# ═══════════════════════════════════════════════════

def resolve_attack(
    attacker: Entity, defender: Entity, weapon: Item,
    attacker_pos: tuple[int, int] | None = None,
    target_pos: tuple[int, int] | None = None,
    grid: Grid[Terrain] | None = None,
    ground_items: list | None = None,
    *,
    hit: bool | None = None,
    roll: int | None = None,
    damage_bonus: int = 0,
    nonlethal: bool = False,
    hidden: bool = False,
    out_of_sight: bool = False,
    guaranteed: bool = False,
) -> dict:
    """完整一次攻击结算（含掩体检查）。

    Args:
        attacker: 攻击者
        defender: 防御者
        weapon: 武器
        attacker_pos: 攻击者坐标（掩体检查用，可选）
        target_pos: 目标坐标（掩体检查用，可选）
        grid: 地形网格（掩体检查用，可选）
        ground_items: 地上物品列表（掩体检查用，可选）
        hit / roll: 预置命中结果与攻击骰。调用方已判定命中时传入（如玩家主攻复用
            execute_attack_roll 阶段已掷出的骰），跳过内部命中检定直接结算伤害。
            hit/roll 均为 None 时走完整命中检定。
        damage_bonus: 额外伤害加成（战技/重掷），不参与伤害类型转换。
        nonlethal: 击晕模式（阶段9）。True 且近战 + 伤害未超 2×max_hp + 会致死时，
            改为 HP=1 + 昏迷，而非死亡。
        guaranteed: 必定命中（如魔法飞弹）。命中检定未通过时改为刚好成功的点数，
            必定命中（见 hit_check）。

    Returns:
        {
            "hit": bool,
            "critical": bool,
            "roll": int,
            "location": str | None,
            "damage": int,
            "blocked_by_cover": bool,
            "cover_pos": tuple | None,
            "damage_type": str,
            "class_leveled": bool,
        }
    """
    preset_hit = hit is not None
    # 护盾术：承受一次攻击（即使未命中）后消散
    if defender.has_status("shield"):
        defender.remove_status("shield")
    if hit is None:
        adv = compute_attack_adv(attacker, defender, weapon,
                                 attacker_pos=attacker_pos, defender_pos=target_pos,
                                 hidden=hidden, out_of_sight=out_of_sight)
        hit, roll = hit_check(attacker, defender, weapon, adv=adv, guaranteed=guaranteed)
    if not hit:
        # 未命中 → 削韧
        reduce_tenacity(defender, roll)
        return {"hit": False, "critical": False, "roll": roll,
                "location": None, "damage": 0,
                "blocked_by_cover": False, "cover_pos": None,
                "damage_type": normalize_damage_type(weapon.damage_type)}

    # 掩体检查（仅远程武器真实命中检定，需要坐标和地形网格）。
    # 玩家主攻已在 execute_attack_roll 阶段处理过掩体，预置 hit 时不重复检查。
    if not preset_hit and weapon.weapon_type == "ranged" and attacker_pos and target_pos and grid:
        blocked, cover_pos = resolve_cover_line(
            roll, attacker_pos, target_pos, grid, weapon.weapon_type,
            ground_items=ground_items,
        )
        if blocked:
            reduce_tenacity(defender, roll)  # 掩体阻挡，等效未命中
            return {"hit": False, "critical": False, "roll": roll,
                    "location": None, "damage": 0,
                    "blocked_by_cover": True, "cover_pos": cover_pos,
                    "damage_type": normalize_damage_type(weapon.damage_type)}

    critical = (roll == 20)
    location = roll_hit_location(defender.body_type)
    damage = roll_damage(weapon, attacker, critical=critical)

    # 属性伤害附加效果（如灼烧）
    sd = getattr(weapon, 'special_damage', None)
    if sd and _check_special_condition(weapon, sd):
        sd_type = sd.get("type", "")
        effect_handler = _SPECIAL_DAMAGE_EFFECTS.get(sd_type)
        if effect_handler:
            effect_handler(defender, location)

    # 伤害类型归一化：穿刺/挥砍/力场 → 一律钝击（阶段10补丁）
    dmg_type = normalize_damage_type(weapon.damage_type)

    # 战技/重掷加成
    damage += damage_bonus

    # 伤害类型修正（按归一化后的类型结算抗性/易伤/免疫）
    damage = apply_damage_type_modifiers(damage, dmg_type, defender)

    # 应用伤害（统一走 take_damage：扣血 + 打断标记；take_damage 内部再次归一化类型）
    # 击晕模式（阶段9）：近战 + 非致命 + 未超 2×max_hp + 会致死 → HP=1 + 昏迷
    if (nonlethal and weapon.weapon_type == "melee"
            and defender.hp - damage < 1
            and damage < 2 * defender.max_hp):
        defender.hp = 1
        defender._interrupted = True
        defender.add_status("昏迷")
    else:
        defender.take_damage(damage, dmg_type, critical=critical)

    result = {"hit": True, "critical": critical, "roll": roll,
              "location": location, "damage": damage,
              "blocked_by_cover": False, "cover_pos": None,
              "damage_type": dmg_type}
    # 命中 → 攻击者获得职业经验（实体通用，NPC 同样累积）
    result["class_leveled"] = attacker.grant_class_exp()
    return result


# ═══════════════════════════════════════════════════
# 削韧
# ═══════════════════════════════════════════════════

def reduce_tenacity(target: Entity, d20_roll: int) -> None:
    """未命中时削减目标韧性。公式: max(roll // 5, 1)。
    韧性归零 → 陷入 incapacitated 状态。
    韧性最低为 0。
    """
    reduction = max(d20_roll // 5, 1)
    target.tenacity = max(0, target.tenacity - reduction)
    if target.tenacity == 0 and not target.has_status("incapacitated"):
        target.add_status("incapacitated")


# ═══════════════════════════════════════════════════
# 自动命中攻击（如魔法飞弹）
# ═══════════════════════════════════════════════════

class AutoHitAttack:
    """无需命中检定的攻击（如魔法飞弹）。必定命中：检定未通过时改为刚好成功的点数。"""

    def __init__(self, damage_dice: str, missiles: int, damage_type: str):
        self.damage_dice = damage_dice
        self.missiles = missiles
        self.damage_type = normalize_damage_type(damage_type)

    def resolve(self, attacker: Entity | None, defender: Entity | None) -> list[int]:
        """结算必定命中伤害。返回每发导弹的伤害列表。"""
        count, sides = parse_dice(self.damage_dice)
        results = []
        for _ in range(self.missiles):
            dmg = roll_dice(count, sides)
            if defender:
                if attacker is not None:
                    # 必定命中：命中检定未通过时改为刚好成功的点数
                    hit, roll = hit_check(attacker, defender, mod=attacker.stat_adjust("int"),
                                          guaranteed=True)
                dmg = apply_damage_type_modifiers(dmg, self.damage_type, defender)
            results.append(dmg)
        if defender:
            total = sum(results)
            defender.take_damage(total, self.damage_type)
        return results
