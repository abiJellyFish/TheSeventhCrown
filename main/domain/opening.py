"""新开场：选用图上已有角色，倒地半血并授予破旧卷轴。"""
from domain.entity import STATUS_PRONE
from domain.grid import DIRS_8
from domain.loot import grant_item
from domain.trade import load_item

ELDER_KEY = "村庄长老"
# 玩家站在长老东邻，偏移属于 DIRS_8 周围一圈。
_PLAYER_DELTA = (1, 0)


def _find_entity(state, key: str):
    return next(
        (
            creature
            for creature, _ in state.entities
            if getattr(creature, "template_name", None) == key or creature.name == key
        ),
        None,
    )


def bind_selected_character(state, char_key: str):
    """把地图上已有的所选角色设为受控者，挪到长老相邻格。未选角色保持 NPC。"""
    if _PLAYER_DELTA not in DIRS_8:
        raise RuntimeError("开场偏移必须是周围一圈")
    player = _find_entity(state, char_key)
    if player is None:
        raise ValueError(f"角色数据不存在: {char_key}")
    elder = _find_entity(state, ELDER_KEY)
    if elder is None:
        raise ValueError("缺少村庄长老")
    elder_pos = state.get_entity_pos(elder)
    dest = (
        elder_pos[0] + _PLAYER_DELTA[0],
        elder_pos[1] + _PLAYER_DELTA[1],
        elder_pos[2],
    )
    occupant = state.get_entity_at(dest[0], dest[1], z=dest[2])
    if occupant is not None and occupant is not player:
        raise RuntimeError(f"开场格子被占据: {dest}")
    state.set_controlled(player)
    state.controlled_entity_pos = dest
    state.invalidate_spatial_cache()
    return player


def apply_new_game_opening(state) -> None:
    """倒地、半血、开场日志、授予破旧卷轴。"""
    player = state.controlled_entity
    if player is None:
        raise RuntimeError("开场时没有受控角色")
    position = state.get_entity_pos(player)
    player.add_status(STATUS_PRONE)
    player.hp = player.max_hp // 2
    state.emit_log("你从高空坠落而下，似乎失去了许多记忆", position=position)
    state.emit_log(
        "一位身披长袍的老者站在一边，看到你苏醒，神情激动地拿出一张破旧的卷轴。",
        position=position,
    )
    scroll = load_item("破旧卷轴")
    if scroll is None:
        raise RuntimeError("缺少物品：破旧卷轴")
    grant_item(player, scroll, state)
