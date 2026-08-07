"""休息系统 —— 短休/长休 + 舒适加成。"""

from core.entity import Player
from core.grid import Grid
from core.movement import Terrain
from core.pendulum import PendulumClock

SHORT_REST_PENDULUMS = 300
LONG_REST_PENDULUMS = 1500


def is_comfortable(pos: tuple[int, int], terrain_map: Grid[Terrain]) -> bool:
    """判断位置是否舒适（室内/床上）。检查地形标记。"""
    col, row = pos
    # 检查周围 8 格是否至少有 2 面墙（室内）
    wall_count = 0
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if dc == 0 and dr == 0:
                continue
            nc, nr = col + dc, row + dr
            if nc < 0 or nr < 0 or nc >= terrain_map.width or nr >= terrain_map.height:
                continue
            if terrain_map[nc, nr] == Terrain.WALL:
                wall_count += 1
    return wall_count >= 2


def short_rest(player: Player, clock: PendulumClock,
               terrain_map: Grid[Terrain] | None = None,
               pos: tuple[int, int] | None = None) -> dict:
    """短休：300 钟摆，恢复 50% HP/MP，移除 1 层力竭。

    Returns:
        {"hp_restored": int, "mp_restored": int}
    """
    comfort = False
    if terrain_map and pos:
        comfort = is_comfortable(pos, terrain_map)

    multiplier = 2 if comfort else 1
    hp_restore = (player.max_hp // 2) * multiplier
    mp_restore = (player.max_mp // 2) * multiplier

    player.hp = min(player.max_hp, player.hp + hp_restore)
    player.mp = min(player.max_mp, player.mp + mp_restore)

    # 推进时间
    for _ in range(SHORT_REST_PENDULUMS):
        clock.tick_action(cost=1.0)

    return {"hp_restored": hp_restore, "mp_restored": mp_restore}


def long_rest(player: Player, clock: PendulumClock,
              terrain_map: Grid[Terrain] | None = None,
              pos: tuple[int, int] | None = None) -> dict:
    """长休：1500 钟摆，恢复 100% HP/MP，移除所有力竭。

    Returns:
        {"hp_restored": int, "mp_restored": int}
    """
    comfort = False
    if terrain_map and pos:
        comfort = is_comfortable(pos, terrain_map)

    multiplier = 2 if comfort else 1
    hp_restore = player.max_hp * multiplier
    mp_restore = player.max_mp * multiplier

    player.hp = min(player.max_hp, player.hp + hp_restore)
    player.mp = min(player.max_mp, player.mp + mp_restore)

    for _ in range(LONG_REST_PENDULUMS):
        clock.tick_action(cost=1.0)

    return {"hp_restored": hp_restore, "mp_restored": mp_restore}
