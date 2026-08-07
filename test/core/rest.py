"""休息系统 —— 短休/长休 + 舒适加成。"""

from core.entity import Player
from core.grid import Grid
from core.movement import Terrain
from core.pendulum import PendulumClock

SHORT_REST_PENDULUMS = 300
LONG_REST_PENDULUMS = 1500


def is_comfortable(pos: tuple[int, int], terrain_map: Grid[Terrain],
                   bed_positions: set[tuple[int, int]] | None = None) -> bool:
    """判断位置是否舒适（室内/床上附近）。

    舒适条件（满足任一即可）：
    - 周围 8 格至少 2 面墙（室内）
    - 自身或相邻 8 格有床
    """
    col, row = pos

    # 检查床：自身或相邻格
    if bed_positions:
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if (col + dc, row + dr) in bed_positions:
                    return True

    # 检查室内（周围墙壁）
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
               pos: tuple[int, int] | None = None,
               bed_positions: set[tuple[int, int]] | None = None) -> dict:
    """短休：300 钟摆，恢复 50% HP/MP。

    Returns:
        {"hp_restored": int, "mp_restored": int, "comfort": bool}
    """
    comfort = False
    if terrain_map and pos:
        comfort = is_comfortable(pos, terrain_map, bed_positions)

    multiplier = 2 if comfort else 1
    hp_restore = (player.max_hp // 2) * multiplier
    mp_restore = (player.max_mp // 2) * multiplier

    player.hp = min(player.max_hp, player.hp + hp_restore)
    player.mp = min(player.max_mp, player.mp + mp_restore)

    for _ in range(SHORT_REST_PENDULUMS):
        clock.tick_action(cost=1.0)

    return {"hp_restored": hp_restore, "mp_restored": mp_restore, "comfort": comfort}


def long_rest(player: Player, clock: PendulumClock,
              terrain_map: Grid[Terrain] | None = None,
              pos: tuple[int, int] | None = None,
              bed_positions: set[tuple[int, int]] | None = None) -> dict:
    """长休：1500 钟摆，恢复 100% HP/MP。

    Returns:
        {"hp_restored": int, "mp_restored": int, "comfort": bool}
    """
    comfort = False
    if terrain_map and pos:
        comfort = is_comfortable(pos, terrain_map, bed_positions)

    multiplier = 2 if comfort else 1
    hp_restore = player.max_hp * multiplier
    mp_restore = player.max_mp * multiplier

    player.hp = min(player.max_hp, player.hp + hp_restore)
    player.mp = min(player.max_mp, player.mp + mp_restore)

    for _ in range(LONG_REST_PENDULUMS):
        clock.tick_action(cost=1.0)

    return {"hp_restored": hp_restore, "mp_restored": mp_restore, "comfort": comfort}
