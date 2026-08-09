"""先攻排序。"""

from core.entity import Creature
from core.dice import roll_d20


def roll_initiative(entities: list[Creature]) -> list[Creature]:
    """投先攻并排序。返回先攻从高到低的生物列表。"""
    scored = []
    for e in entities:
        init = roll_d20() + e.initiative_bonus()
        scored.append((init, e.faction, id(e), e))
    # 按先攻降序；平局时非敌对优先
    scored.sort(key=lambda x: (x[0], x[1] != "hostile", x[2]), reverse=True)
    return [e for _, _, _, e in scored]
