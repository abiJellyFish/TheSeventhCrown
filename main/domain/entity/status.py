"""状态效果数据类与力竭/中毒/窒息规则。"""
from dataclasses import dataclass

STATUS_POISONED = "中毒"
STATUS_EXHAUSTED = "力竭"
STATUS_SUFFOCATING = "窒息"
STATUS_SLEEP = "睡眠"
STARVE_PENDULUMS = 5000
MAX_EXHAUSTION = 10


@dataclass
class StatusEffect:
    """一条独立状态。duration=钟摆；end_event='combat_round' 时用 rounds_left。"""
    name: str
    duration: int | None = None
    end_event: str | None = None
    rounds_left: int | None = None


def status_label(creature, effect: StatusEffect) -> str:
    """面板显示名；力竭带等级。"""
    if effect.name == STATUS_EXHAUSTED:
        return f"{STATUS_EXHAUSTED}{getattr(creature, 'exhaustion_level', 0)}"
    return effect.name


def format_status_names(creature) -> list[str]:
    """当前状态的显示名列表。"""
    return [status_label(creature, effect) for effect in creature.statuses]


def effective_max_hp(creature) -> int:
    """力竭 7+ 时生命上限减半，至少 1。"""
    base = creature.max_hp
    if getattr(creature, "exhaustion_level", 0) >= 7:
        return max(1, base // 2)
    return base


def movement_speed_halved(creature) -> bool:
    """倒地、躲藏、力竭≥3 只减半一次。"""
    return (
        creature.has_status("prone")
        or creature.has_status("hiding")
        or getattr(creature, "exhaustion_level", 0) >= 3
    )


def apply_poisoned(creature, duration: int | None = None) -> bool:
    """施加中毒。poison_immune 免疫。"""
    traits = getattr(creature, "traits", None) or []
    if "poison_immune" in traits:
        return False
    creature.add_status(STATUS_POISONED, duration)
    return True


def apply_sleep(creature, duration: int | None = None) -> bool:
    """施加睡眠。sleep_immune 免疫。"""
    traits = getattr(creature, "traits", None) or []
    if "sleep_immune" in traits:
        return False
    creature.add_status(STATUS_SLEEP, duration)
    return True


def gain_exhaustion(creature) -> int:
    """获得力竭：已有则不变，没有则 1 级。"""
    level = getattr(creature, "exhaustion_level", 0)
    if level < 1:
        return set_exhaustion_level(creature, 1)
    return level


def raise_exhaustion(creature, n: int = 1) -> int:
    """提升（或降低）力竭等级。"""
    level = getattr(creature, "exhaustion_level", 0)
    return set_exhaustion_level(creature, level + n)


def set_exhaustion_level(creature, level: int) -> int:
    """唯一写入入口。小于 1 摆脱力竭；达到 10 进入濒死。"""
    if level < 1:
        level = 0
    if level > MAX_EXHAUSTION:
        level = MAX_EXHAUSTION
    previous = getattr(creature, "exhaustion_level", 0)
    creature.exhaustion_level = level
    if level < 1:
        creature.remove_status(STATUS_EXHAUSTED)
    else:
        creature.add_status(STATUS_EXHAUSTED)
    if level >= 9:
        creature.add_status("不可移动")
    elif previous >= 9:
        creature.remove_status("不可移动")
    if creature.hp > effective_max_hp(creature):
        creature.hp = effective_max_hp(creature)
    if level >= 10:
        if creature.hp > 0:
            creature.hp = 0
        if not creature.is_dead and not creature.has_status("濒死"):
            creature._enter_dying()
    return level
