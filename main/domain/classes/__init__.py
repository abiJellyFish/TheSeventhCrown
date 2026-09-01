"""职业和魔法领域的统一进度配置。"""

from dataclasses import dataclass, field

ALL_CLASS_KEYS = ("fighter", "mage", "rogue")

CLASS_DISPLAY_NAMES = {
    "fighter": "战士",
    "mage": "魔法使",
    "rogue": "游荡者",
}


@dataclass(frozen=True)
class ClassLevel:
    """职业等级奖励。"""

    requirement: str = ""
    abilities: tuple[str, ...] = ()
    title: str = ""
    spell_slots: dict[str, int] = field(default_factory=dict)
    max_mp: int | None = None


@dataclass(frozen=True)
class DomainLevel:
    """魔法领域等级奖励。"""

    requirement: str = ""
    talent: str = ""
    spells: tuple[str, ...] = ()


FIGHTER_PROGRESSION = {
    0: ClassLevel(abilities=("削韧",)),
    1: ClassLevel(abilities=("重整旗鼓",), title="见习战士"),
    2: ClassLevel(abilities=("横扫",)),
    3: ClassLevel(abilities=("缴械", "扫腿")),
    4: ClassLevel(abilities=("放大创口",)),
}

MAGE_PROGRESSION = {
    0: ClassLevel(),
    1: ClassLevel(
        requirement="domain_talent",
        spell_slots={"1": 2},
        max_mp=100,
        title="见习魔法使",
    ),
    2: ClassLevel(),
}

ROGUE_PROGRESSION = {0: ClassLevel(abilities=("刺杀",))}

CLASS_THRESHOLDS = {
    "fighter": (0, 1, 3, 5, 7),
    "mage": (0, 1, 3),
    "rogue": (0,),
}

CLASS_EXP_BY_WEAPON_CATEGORY = {"simple": 0.01, "martial": 0.02}
CLASS_EXP_MANEUVER = 0.05

WEAPON_CATEGORIES = ("simple", "martial", "shield")
ARMOR_CATEGORIES = ("clothing", "light", "medium", "heavy")

_PROGRESSION = {
    "fighter": FIGHTER_PROGRESSION,
    "mage": MAGE_PROGRESSION,
    "rogue": ROGUE_PROGRESSION,
}

DOMAIN_PROGRESSION = {
    "evocation": {
        0: DomainLevel(),
        1: DomainLevel(requirement="intelligence_check", talent="evocation"),
    },
    "abjuration": {
        0: DomainLevel(),
        1: DomainLevel(requirement="intelligence_check", talent="abjuration"),
    },
}

DOMAIN_THRESHOLDS = {"evocation": (0, 1), "abjuration": (0, 1)}

ABILITY_LEVELS = {
    "削韧": ("fighter", 0),
    "重整旗鼓": ("fighter", 1),
    "横扫": ("fighter", 2),
    "缴械": ("fighter", 3),
    "扫腿": ("fighter", 3),
    "刺杀": ("rogue", 0),
    "放大创口": ("fighter", 4),
}

COMBAT_ABILITY_DEFS = {
    "削韧": {"kind": "lower", "ap_extra": 0, "effect": "tenacity"},
    "重整旗鼓": {"kind": "lower", "ap_extra": 10, "effect": "recover_tenacity", "value": 3},
    "横扫": {"kind": "maneuver", "ap_extra": 20, "effect": "sweep", "conditions": ["melee"]},
    "缴械": {"kind": "maneuver", "ap_extra": 10, "effect": "disarm", "save_stat": "str"},
    "扫腿": {"kind": "lower", "ap_extra": 20, "effect": "knockdown", "save_stat": "dex", "conditions": ["adjacent"]},
    "刺杀": {"kind": "maneuver", "ap_extra": 0, "effect": "damage_multiplier",
             "damage_multiplier": 2, "conditions": ["melee", "light", "behind_adjacent"],
             "desc": "你发动致命一击，造成的伤害翻倍"},
    "放大创口": {"kind": "maneuver", "ap_extra": 20, "effect": "bleeding",
                 "conditions": ["melee", "bleeding"],
                 "bleeding_stacks": 2,
                 "desc": "目标处于流血状态时，附加2次流血"},
}


def class_level_for_exp(class_name: str, experience: float) -> int:
    """根据总经验返回已满足的最高职业等级。"""
    thresholds = CLASS_THRESHOLDS.get(class_name)
    if thresholds is None:
        raise ValueError(f"未知职业：{class_name}")
    return max(level for level, required in enumerate(thresholds) if experience >= required)


def domain_level_for_exp(domain: str, experience: float) -> int:
    """根据总经验返回已满足的最高领域等级。"""
    thresholds = DOMAIN_THRESHOLDS.get(domain)
    if thresholds is None:
        raise ValueError(f"未知魔法领域：{domain}")
    return max(level for level, required in enumerate(thresholds) if experience >= required)


def proficiency_level(experience: float) -> int:
    """根据训练经验返回熟练项等级，最高为+5。"""
    if experience < 5:
        return 0
    return min(5, 1 + int((experience - 5) // 10))


def expertise_level(experience: float) -> int:
    """根据训练经验返回专精项等级，最高为+5。"""
    if experience < 10:
        return 0
    return min(5, 1 + int((experience - 10) // 10))


def available_abilities(creature) -> set[str]:
    """返回实体当前职业等级已获得的能力名称。"""
    class_name = creature.char_class
    level = effective_level_for_class(creature, class_name) if class_name else 0
    progression = _PROGRESSION.get(class_name, {})
    abilities: set[str] = set()
    for granted_level, rewards in progression.items():
        if granted_level <= level:
            abilities.update(rewards.abilities)
    return abilities


def combat_abilities(creature, kind: str, target=None, weapon=None,
                     attacker_pos=None, target_pos=None) -> list[dict]:
    """返回当前职业等级获得的指定类型动作。"""
    abilities = available_abilities(creature)
    return [
        {"name": name, **COMBAT_ABILITY_DEFS[name]}
        for name in abilities
        if COMBAT_ABILITY_DEFS[name]["kind"] == kind
        and (
            target is None and weapon is None
            and attacker_pos is None and target_pos is None
            or action_conditions_met(COMBAT_ABILITY_DEFS[name], creature, target,
                                     weapon, attacker_pos, target_pos)
        )
    ]


def action_conditions_met(action: dict, attacker, target=None, weapon=None,
                          attacker_pos=None, target_pos=None) -> bool:
    """按条件标识统一判定战斗动作是否可用。"""
    from domain.movement import is_back_sector
    for condition in action.get("conditions", ()):
        if condition == "melee" and getattr(weapon, "weapon_type", None) != "melee":
            return False
        if condition == "light" and "light" not in (getattr(weapon, "properties", None) or []):
            return False
        if condition in ("adjacent", "behind_adjacent"):
            if target is None or attacker_pos is None or target_pos is None:
                return False
        if condition == "bleeding" and (target is None or not target.has_status("流血")):
            return False
            from domain.combat.shape import weapon_melee_reach
            reach = weapon_melee_reach(weapon, attacker)
            if max(abs(attacker_pos[0] - target_pos[0]),
                   abs(attacker_pos[1] - target_pos[1])) > reach:
                return False
        if condition == "behind_adjacent":
            delta = (attacker_pos[0] - target_pos[0],
                     attacker_pos[1] - target_pos[1])
            if not is_back_sector(getattr(target, "facing", (0, 1)), *delta):
                return False
    return True


def _route_experience(creature, class_name: str) -> float:
    """读取职业路线总经验（主职业与 class_exp 对齐）。"""
    exp = creature.class_experience.get(class_name, 0.0)
    if class_name == creature.char_class:
        exp = max(exp, creature.class_exp)
    return exp


def effective_level_for_class(creature, class_name: str) -> int:
    """按总经验与职业门槛返回指定路线的有效等级。"""
    if not class_name:
        return 0
    exp = _route_experience(creature, class_name)
    level = class_level_for_exp(class_name, exp)
    if class_name == "mage" and level >= 1:
        requirement = MAGE_PROGRESSION.get(1, ClassLevel()).requirement
        if requirement == "domain_talent" and not creature.domain_talents:
            return 0
    return level


def effective_class_level(creature) -> int:
    """按主职业返回有效等级。"""
    if not creature.char_class:
        return 0
    return effective_level_for_class(creature, creature.char_class)


def ensure_class_progress(creature) -> None:
    """初始化所有职业路线为 0 级，保留已有经验。"""
    if creature._class is None:
        from domain.entity_components import ClassComponent
        creature._class = ClassComponent(char_class=creature.char_class)
    for key in ALL_CLASS_KEYS:
        creature.class_levels.setdefault(key, 0)
        creature.class_experience.setdefault(key, 0.0)


def sync_all_titles(creature) -> None:
    """根据各路线有效等级补发称号（读档/预设等级时）。"""
    ensure_class_progress(creature)
    for class_name in ALL_CLASS_KEYS:
        level = effective_level_for_class(creature, class_name)
        apply_level_rewards(creature, class_name, 0, level)


def apply_level_rewards(creature, class_name: str, old_level: int, new_level: int) -> None:
    """升级时发放称号等奖励。"""
    progression = _PROGRESSION.get(class_name, {})
    for level in range(old_level + 1, new_level + 1):
        rewards = progression.get(level)
        if rewards and rewards.title and rewards.title not in creature.titles:
            creature.titles.append(rewards.title)


def class_exp_progress(class_name: str, experience: float) -> float:
    """返回当前等级到下一级的 0~1 进度。"""
    thresholds = CLASS_THRESHOLDS.get(class_name)
    if thresholds is None:
        return 0.0
    level = class_level_for_exp(class_name, experience)
    if level >= len(thresholds) - 1:
        return 1.0
    start, end = thresholds[level], thresholds[level + 1]
    return min(1.0, max(0.0, (experience - start) / (end - start)))


def format_class_route_lines(creature) -> list[str]:
    """生成各职业路线的等级与经验条文本行。"""
    ensure_class_progress(creature)
    lines: list[str] = []
    for key in ALL_CLASS_KEYS:
        label = CLASS_DISPLAY_NAMES.get(key, key)
        level = effective_level_for_class(creature, key)
        exp = _route_experience(creature, key)
        progress = class_exp_progress(key, exp)
        bar = "+" * int(progress * 10) + "_" * (10 - int(progress * 10))
        lines.append(f"  {label} Lv.{level}  [{bar}] {exp:.2f}")
    return lines
