"""先攻排序。"""

from core.entity import Creature
from core.dice import roll_d20


def roll_initiative(entities: list[Creature]) -> list[Creature]:
    """投先攻并排序。返回先攻从高到低的生物列表。"""
    FACTION_ORDER = {"守序": 0, "中立": 1, "混乱": 2}
    scored = []
    for e in entities:
        init = roll_d20() + e.initiative_bonus()
        scored.append((init, FACTION_ORDER.get(e.faction, 1), id(e), e))
    # 按先攻降序；平局时守序优先
    scored.sort(key=lambda x: (x[0], -x[1], x[2]), reverse=True)
    return [e for _, _, _, e in scored]
