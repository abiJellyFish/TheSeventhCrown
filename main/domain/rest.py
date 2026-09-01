"""休息系统 —— 短休/长休 + 舒适加成。"""

from domain.entity import Entity
from domain.grid import Grid
from domain.obstacle import is_full_obstacle
from domain.movement import Terrain
from domain.pendulum import PendulumClock

SHORT_REST_PENDULUMS = 300
LONG_REST_PENDULUMS = 1500


def is_comfortable(pos: tuple[int, int], terrain_map: Grid[Terrain],
                   entities=None, ground_items=None) -> bool:
    """判断位置是否舒适（室内/床上附近）。

    舒适条件（满足任一即可）：
    - 周围 8 格至少 2 面墙（室内）
    - 自身或相邻 8 格有床
    """
    col, row = pos

    # 检查床：自身或相邻格是否有 BED 地形
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if terrain_map.within_bounds(col + dc, row + dr) and any(
                item_pos == (col + dc, row + dr) and item.name == "床铺"
                for item, item_pos in (ground_items or ())
            ):
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
            if any(
                item_pos == (nc, nr) and is_full_obstacle(item)
                for item, item_pos in (ground_items or ())
            ):
                wall_count += 1
    return wall_count >= 2


def _rest(player: Entity, clock: PendulumClock, pendulums: int,
          hp_fraction: float, mp_fraction: float,
          terrain_map: Grid[Terrain] | None = None,
          pos: tuple[int, int] | None = None,
          ground_items=None) -> dict:
    """休息通用逻辑：短休/长休差异仅钟摆数和恢复比例。"""
    comfort = False
    if terrain_map and pos:
        comfort = is_comfortable(pos, terrain_map, ground_items=ground_items)

    multiplier = 2 if comfort else 1
    hp_restore = int(player.max_hp * hp_fraction * multiplier)
    mp_restore = int(player.max_mp * mp_fraction * multiplier)

    player.hp = min(player.max_hp, player.hp + hp_restore)
    player.mp = min(player.max_mp, player.mp + mp_restore)

    # 休息期间锁定饮食值，防止饥饿致死
    was_locked = player.food_locked
    player.food_locked = True
    # 清除上一次行动残留的打断标记（倒地/受伤等），仅休息期间的新伤害才打断
    player._interrupted = False
    interrupted = False
    for _ in range(pendulums):
        clock.tick_action(cost=1.0)
        if player._interrupted:
            player._interrupted = False
            interrupted = True
            break
    player.food_locked = was_locked

    return {"hp_restored": hp_restore, "mp_restored": mp_restore,
            "comfort": comfort, "interrupted": interrupted}


def short_rest(player: Entity, clock: PendulumClock,
               terrain_map: Grid[Terrain] | None = None,
               pos: tuple[int, int] | None = None,
               ground_items=None) -> dict:
    """短休：300 钟摆，恢复 50% HP/MP。"""
    return _rest(player, clock, SHORT_REST_PENDULUMS, 0.5, 0.5,
                 terrain_map=terrain_map, pos=pos, ground_items=ground_items)


def long_rest(player: Entity, clock: PendulumClock,
              terrain_map: Grid[Terrain] | None = None,
              pos: tuple[int, int] | None = None,
              ground_items=None) -> dict:
    """长休：1500 钟摆，恢复 100% HP/MP。"""
    return _rest(player, clock, LONG_REST_PENDULUMS, 1.0, 1.0,
                 terrain_map=terrain_map, pos=pos, ground_items=ground_items)
