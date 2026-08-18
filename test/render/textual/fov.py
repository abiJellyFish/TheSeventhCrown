"""FOV 与火把光源同步 —— 玩家视野重算与持有光源同步。"""

from core.fov import LightLevel, compute_fov
from core.game_state import GameState

def _update_fov(state: GameState) -> None:
    ox, oy = state.player_pos

    # 同步玩家持有的火把光源位置
    _sync_torch_light(state)

    transparent = state._get_transparent_grid()  # 复用缓存，仅地形变更时重建
    light = state._build_light_grid()
    bright, dim = compute_fov(transparent, (ox, oy), state.player.vision_range,
                               light, state.player.darkvision_range > 0,
                               state.player.darkvision_range,
                               facing=state.player.facing)
    state.fov_bright = bright
    state.fov_dim = dim
    state.fov_cache = bright | dim
    # 事件驱动检定：玩家视野重算时对新进入视野实体被动感知
    state._on_fov_recompute(state.player)
    # 陷阱与线索被动发现（阶段5）：视野内一次性感知检定接入 spot_memo
    state._maybe_discover_spots(state.player)


def _sync_torch_light(state: GameState) -> None:
    """将玩家持有的已点燃火把光源同步到玩家当前位置。"""
    from core.fov import LightLevel
    player = state.player
    # 检查装备栏和背包中的已点燃火把
    for item in list(player.equipment.values()) + list(player.inventory):
        if item is None:
            continue
        ls = item.light
        if ls and ls.condition == "lit":
            # 移除旧位置的光源
            old_positions = [p for p in list(state.light_sources.keys())
                           if state.light_sources[p] == (ls.radius, LightLevel.BRIGHT)]
            for old_pos in old_positions:
                del state.light_sources[old_pos]
            # 注册到新位置
            state.register_light(state.player_pos, ls.radius, LightLevel.BRIGHT)
            return
