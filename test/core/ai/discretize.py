"""状态离散化 —— 将 NPC 连续状态转为离散键集合。

整个 AI 系统唯一使用 if-else 的函数。
"""

from core.entity import Entity


def discretize_state(
    npc: Entity,
    enemy_count: int = 0,
    ally_count: int = 0,
    power_ratio: float = 1.0,
) -> frozenset[str]:
    """将 NPC 当前状态离散化为键集合。

    Args:
        npc: NPC 实例
        enemy_count: 视野内敌人数量
        ally_count: 附近盟友数量
        power_ratio: 实力比（我方/敌方）

    Returns:
        状态键的不可变集合
    """
    keys: set[str] = set()

    # HP
    r = npc.hp / max(npc.max_hp, 1)
    if r <= 0:
        keys.add("hp:dead")
    elif r < 0.2:
        keys.add("hp:critical")
    elif r < 0.5:
        keys.add("hp:low")
    else:
        keys.add("hp:healthy")

    # 战力对比
    if power_ratio < 0.4:
        keys.add("power:heavily_outmatched")
    elif power_ratio < 0.7:
        keys.add("power:disadvantage")
    elif power_ratio < 1.3:
        keys.add("power:even")
    else:
        keys.add("power:advantage")

    # 盟友
    if ally_count == 0:
        keys.add("social:alone")
    elif ally_count < 3:
        keys.add("social:few_allies")
    else:
        keys.add("social:many_allies")

    # 敌人
    if enemy_count == 0:
        keys.add("threat:none")
    else:
        keys.add("threat:visible")

    # 状态标记
    if npc.has_status("灼烧"):
        keys.add("灼烧")
    if npc.has_status("on_fire"):
        keys.add("status:on_fire")
    if npc.has_status("poisoned"):
        keys.add("status:poisoned")
    if npc.has_status("prone"):
        keys.add("status:prone")
    if npc.has_status("hiding"):
        keys.add("status:hiding")
    # 用 food_locked 判断
    if not getattr(npc, "food_locked", True):
        ratio = npc.food_value / 15000
        if ratio < 0.2:
            keys.add("need:starving")
            keys.add("need:hungry")  # starving 也是 hungry，确保 forage/eat_food 可匹配
        elif ratio < 0.5:
            keys.add("need:hungry")
        else:
            keys.add("need:full")

    # 日程和性格
    keys.add(f"sched:{npc.schedule}")
    keys.add(f"brave:{npc.bravery_tier}")
    keys.add(f"aggr:{npc.aggression_tier}")

    return frozenset(keys)
