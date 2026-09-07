"""先攻排序与轮转名单。"""

from domain.entity import Entity
from domain.checks import KIND_ABILITY, resolve_check


FACTION_ORDER = {"守序": 0, "中立": 1, "混乱": 2}


def _sort_key(entity: Entity):
    faction = FACTION_ORDER.get(entity.faction, 1)
    return (getattr(entity, "initiative_roll", 0), -faction, id(entity))


def _roll_one(entity: Entity) -> int:
    _, init = resolve_check(entity, KIND_ABILITY, entity.initiative_bonus())
    entity.initiative_roll = init
    return init


def roll_initiative(entities: list[Entity]) -> list[Entity]:
    """投先攻并排序。返回先攻从高到低的生物列表。"""
    for entity in entities:
        _roll_one(entity)
    return sorted(entities, key=_sort_key, reverse=True)


def join_rotation(state, creature: Entity | None) -> bool:
    """新生物掷先攻后插入轮转名单。已在名单中则忽略。"""
    if creature is None or creature.is_dead:
        return False
    if any(participant is creature for participant in state.combat_initiative):
        return False
    if not state.in_combat:
        enter_rotation(state, extra=(creature,))
        return creature in state.combat_initiative
    _roll_one(creature)
    creature.ap = creature.max_ap
    key = _sort_key(creature)
    insert_at = len(state.combat_initiative)
    for index, existing in enumerate(state.combat_initiative):
        if _sort_key(existing) < key:
            insert_at = index
            break
    current = state.combat_turn_entity
    state.combat_initiative.insert(insert_at, creature)
    if current is not None:
        try:
            state.combat_turn_index = state.combat_initiative.index(current)
        except ValueError:
            pass
    return True


def _unique_living(*groups):
    seen = set()
    members = []
    for group in groups:
        for creature in group:
            if creature is None or creature.is_dead:
                continue
            marker = id(creature)
            if marker in seen:
                continue
            seen.add(marker)
            members.append(creature)
    return members


def enter_rotation(state, extra=()) -> bool:
    """进入轮转：全队与 extra 一起掷先攻。已在轮转则只插入新成员。"""
    party = [member for member in getattr(state, "party", [])]
    newcomers = _unique_living(party, extra)
    if state.in_combat:
        joined = False
        for creature in newcomers:
            joined = join_rotation(state, creature) or joined
        return False
    if not newcomers:
        return False
    state.in_combat = True
    if hasattr(state, "clear_group_move"):
        state.clear_group_move()
    for creature in newcomers:
        creature.ap = creature.max_ap
    state.combat_initiative = roll_initiative(newcomers)
    state.combat_turn_index = 0
    state.combat_turn_entity = (
        state.combat_initiative[0] if state.combat_initiative else None
    )
    return True
