"""借机/反应：触发收集与反应类型表。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.entity import Entity
    from domain.game_state import GameState

REACTION_DEFS = {
    "opportunity_attack": {
        "name": "借机攻击",
        "panel_title": "借机攻击！",
        "log_player": "敌人经过了你的触及范围！",
        "log_npc": "{reactor} 对 {mover} 发动了借机攻击",
    },
    "shield": {
        "name": "护盾术",
        "panel_title": "护盾术！",
        "log_player": "是否施放护盾术？",
        "log_npc": "",
    },
}


def adjacent(a: tuple[int, int], b: tuple[int, int]) -> bool:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(dx, dy) <= 1 and (dx, dy) != (0, 0)


def weapon_ap_cost(item) -> int:
    w = getattr(item, "weapon", None)
    if w is not None:
        return int(getattr(w, "ap_cost", 10) or 10)
    return int(getattr(item, "ap_cost", 10) or 10)


def default_melee_weapon(creature):
    for slot in ("right_hand", "left_hand"):
        item = creature.equipment.get(slot)
        if item is not None and getattr(item, "weapon", None) is not None and item.weapon_type == "melee":
            return item
    from domain.items.item import Weapon
    return Weapon(name="徒手打击", weapon_type="melee", damage="1d4",
                  damage_type="bludgeoning", attack_stat="str", ap_cost=10)


def list_available_reactions(reactor, kind: str = "opportunity_attack") -> list[dict]:
    spec = REACTION_DEFS.get(kind)
    if spec is None:
        raise ValueError(f"unknown reaction kind: {kind}")
    if kind == "shield" and not reactor.has_status("shield"):
        return []
    return [{"kind": kind, **spec}]


def reaction_can_fire(reactor, event: dict) -> bool:
    """当前事件是否可执行。做不到则不应入队或打开面板。"""
    if reactor is None or getattr(reactor, "is_dead", False):
        return False
    kind = event.get("kind")
    checkers = {
        "opportunity_attack": lambda: (
            reactor.ap >= weapon_ap_cost(default_melee_weapon(reactor))
        ),
        "shield": lambda: reactor.has_status("shield"),
    }
    check = checkers.get(kind)
    if check is None:
        raise ValueError(f"unknown reaction kind: {kind}")
    return check()


def collect_opportunity_reactors(state: "GameState", mover, from_pos, to_pos) -> list:
    """返回应对本次移动发动借机的实体（不含 mover）。探索模式或未参战双方不触发。"""
    if not state.in_combat:
        return []
    if mover.has_status("disengaged"):
        return []
    if mover not in state.combat_initiative:
        return []
    out = []
    for creature, pos in state.iter_entities():
        if creature is mover or creature.is_dead:
            continue
        if creature not in state.combat_initiative:
            continue
        was = adjacent(from_pos, pos)
        now = adjacent(to_pos, pos)
        if was != now:
            out.append(creature)
    return out
