"""休息系统 —— 短休/长休 + 舒适加成。效应在完整结束后额外结算。"""

from domain.entity import Entity
from domain.entity.status import (
    STATUS_SUFFOCATING,
    apply_sleep,
    effective_max_hp,
    raise_exhaustion,
    set_exhaustion_level,
)
from domain.grid import Grid
from domain.obstacle import is_full_obstacle
from domain.movement import Terrain
from domain.pendulum import AP_PER_PENDULUM, PendulumClock

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
                item_pos[:2] == (col + dc, row + dr) and item.name == "床铺"
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
                item_pos[:2] == (nc, nr) and is_full_obstacle(item)
                for item, item_pos in (ground_items or ())
            ):
                wall_count += 1
    return wall_count >= 2


def _restore_amount(current: int, maximum: int, fraction: float, multiplier: int) -> int:
    if maximum <= 0:
        return 0
    return int(maximum * fraction * multiplier)


def _apply_rest_effects(creature: Entity, hp_fraction: float, mp_fraction: float,
                        multiplier: int, clear_all_exhaustion: bool,
                        skip_exhaustion: bool) -> dict:
    """完整休息结束后的额外恢复。不改理智/心灵。"""
    hp_restore = _restore_amount(
        creature.hp, effective_max_hp(creature), hp_fraction, multiplier
    )
    mp_restore = _restore_amount(creature.mp, creature.max_mp, mp_fraction, multiplier)
    courage_restore = _restore_amount(
        creature.courage, creature.effective_max_courage, hp_fraction, multiplier
    )
    tenacity_restore = _restore_amount(
        creature.tenacity, creature.tenacity_cap(), hp_fraction, multiplier
    )
    creature.hp = min(effective_max_hp(creature), creature.hp + hp_restore)
    creature.mp = min(creature.max_mp, creature.mp + mp_restore)
    creature.courage = min(creature.effective_max_courage, creature.courage + courage_restore)
    creature.tenacity = min(creature.tenacity_cap(), creature.tenacity + tenacity_restore)
    if not skip_exhaustion:
        if clear_all_exhaustion:
            set_exhaustion_level(creature, 0)
        else:
            raise_exhaustion(creature, -1)
    return {
        "name": creature.name,
        "hp_restored": hp_restore,
        "mp_restored": mp_restore,
        "courage_restored": courage_restore,
        "tenacity_restored": tenacity_restore,
    }


def _rest(player: Entity, clock: PendulumClock, pendulums: int,
          hp_fraction: float, mp_fraction: float,
          terrain_map: Grid[Terrain] | None = None,
          pos: tuple[int, int] | tuple[int, int, int] | None = None,
          ground_items=None,
          resters: list[Entity] | None = None,
          in_rotation: bool = False,
          is_engaged=None) -> dict:
    """先推进时间（自然恢复照常），完整结束后才给休息效应。"""
    resters = list(resters) if resters else [player]
    comfort = False
    if terrain_map and pos:
        comfort = is_comfortable(pos[:2], terrain_map, ground_items=ground_items)
    multiplier = 2 if comfort else 1
    snapshots = []
    stunned = []
    from domain.combat.tenacity import reset_attack_streak
    for creature in resters:
        reset_attack_streak(creature)
        snapshots.append((
            creature,
            creature.food_value == 0,
            creature.has_status(STATUS_SUFFOCATING),
        ))
        if creature.has_status("震慑"):
            stunned.append(creature)
        creature._resting = True
        creature._interrupted = False
        apply_sleep(creature)

    interrupted = False
    remaining = pendulums
    elapsed = 0
    batch = 10
    while remaining > 0:
        step = min(batch, remaining)
        clock.tick_action(cost=float(step))
        elapsed += step
        if in_rotation:
            drain = int(step) * AP_PER_PENDULUM
            for creature in resters:
                creature.ap = max(0, creature.ap - drain)
        if any(creature._interrupted for creature in resters):
            interrupted = True
            break
        if is_engaged is not None and any(is_engaged(creature) for creature in resters):
            interrupted = True
            break
        remaining -= step

    for creature in resters:
        creature._resting = False
        creature.remove_status("睡眠")

    members = []
    if not interrupted:
        clear_all = pendulums == LONG_REST_PENDULUMS
        for creature, hungry, suffocating in snapshots:
            members.append(_apply_rest_effects(
                creature, hp_fraction, mp_fraction, multiplier,
                clear_all_exhaustion=clear_all,
                skip_exhaustion=hungry or suffocating,
            ))
        if clear_all:
            for creature in stunned:
                creature.remove_status("震慑")
    else:
        members = [{
            "name": creature.name,
            "hp_restored": 0,
            "mp_restored": 0,
            "courage_restored": 0,
            "tenacity_restored": 0,
        } for creature in resters]

    first = members[0] if members else {
        "hp_restored": 0, "mp_restored": 0,
        "courage_restored": 0, "tenacity_restored": 0,
    }
    return {
        "hp_restored": first["hp_restored"],
        "mp_restored": first["mp_restored"],
        "courage_restored": first.get("courage_restored", 0),
        "tenacity_restored": first.get("tenacity_restored", 0),
        "comfort": comfort,
        "interrupted": interrupted,
        "elapsed": elapsed,
        "planned": pendulums,
        "members": members,
    }


def short_rest(player: Entity, clock: PendulumClock,
               terrain_map: Grid[Terrain] | None = None,
               pos: tuple[int, int] | None = None,
               ground_items=None, **kwargs) -> dict:
    """短休：300 钟摆，结束后额外恢复 50% 勇气/生命/精神力/韧性。"""
    return _rest(player, clock, SHORT_REST_PENDULUMS, 0.5, 0.5,
                 terrain_map=terrain_map, pos=pos, ground_items=ground_items,
                 **kwargs)


def long_rest(player: Entity, clock: PendulumClock,
              terrain_map: Grid[Terrain] | None = None,
              pos: tuple[int, int] | None = None,
              ground_items=None, **kwargs) -> dict:
    """长休：1500 钟摆，结束后额外恢复全部勇气/生命/精神力/韧性。"""
    return _rest(player, clock, LONG_REST_PENDULUMS, 1.0, 1.0,
                 terrain_map=terrain_map, pos=pos, ground_items=ground_items,
                 **kwargs)
