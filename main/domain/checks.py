"""统一检定入口：命中 / 属性 / 豁免。状态骰修正只写在这里。"""
import domain.dice as dice_mod
from domain.entity.status import STATUS_POISONED

KIND_ATTACK = "attack"
KIND_ABILITY = "ability"
KIND_SAVE = "save"


def status_adv(creature, kind: str) -> int:
    """中毒/力竭对骰子池的净修正。正=优势层数，负=劣势层数。"""
    adv = 0
    level = getattr(creature, "exhaustion_level", 0)
    if kind == KIND_ATTACK and level >= 1:
        adv -= 1
    if kind in (KIND_ABILITY, KIND_SAVE):
        if creature.has_status(STATUS_POISONED):
            adv -= 1
        if level >= 5:
            adv -= 1
    return adv


def _pool(adv: int) -> tuple[int, int]:
    return (adv if adv > 0 else 0, -adv if adv < 0 else 0)


def roll_check_dice(creature, kind: str, extra_adv: int = 0) -> list[int]:
    """按类别汇总状态+场景修正后掷出骰面列表（供玩家选骰）。"""
    advantage, disadvantage = _pool(status_adv(creature, kind) + extra_adv)
    return dice_mod.roll_adv_dice(advantage, disadvantage)


def resolve_check(creature, kind: str, adjust: int = 0, extra_adv: int = 0,
                  chosen_roll: int | None = None) -> tuple[int, int]:
    """统一 D20 检定。返回 (自然面, 含震慑的总分)。"""
    if chosen_roll is not None:
        face = chosen_roll
    else:
        advantage, disadvantage = _pool(status_adv(creature, kind) + extra_adv)
        face = dice_mod.roll_d20(advantage=advantage, disadvantage=disadvantage)
    return face, dice_mod.check_total(creature, face, adjust)


def ability_extra_adv(creature, stat: str, extra_adv: int = 0) -> int:
    """属性检定的场景修正（协助/重伤/护甲），不含中毒力竭。"""
    adv = extra_adv
    if creature.has_status("重伤") and stat in ("str", "dex", "wis"):
        adv -= 1
    if creature.has_status("assisted"):
        adv += 1
        creature.remove_status("assisted")
    armor_penalty = creature.armor_penalty()
    if stat == "str" and armor_penalty["str_disadvantage"]:
        adv -= 1
    if stat == "dex" and armor_penalty["dex_disadvantage"]:
        adv -= 1
    return adv


def ability_check(creature, stat: str, extra_adv: int = 0,
                  chosen_roll: int | None = None) -> int:
    """属性检定：D20 + 属性调整值。昏迷对力/敏/感知自动失败。"""
    if creature.has_status("昏迷") and stat in ("str", "dex", "wis"):
        return -10 ** 9
    adv = ability_extra_adv(creature, stat, extra_adv)
    _, total = resolve_check(
        creature, KIND_ABILITY, creature.stat_adjust(stat), adv, chosen_roll
    )
    return total


def saving_throw(creature, stat: str = "dex", extra_adv: int = 0,
                 chosen_roll: int | None = None) -> tuple[int, int]:
    """豁免检定。回避时敏捷豁免额外优势。返回 (自然面, 总分)。"""
    adv = extra_adv
    if stat == "dex" and creature.has_status("dodge"):
        adv += 1
    return resolve_check(
        creature, KIND_SAVE, creature.stat_adjust(stat), adv, chosen_roll
    )
