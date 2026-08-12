"""物品操作 —— 物品操作菜单生成、丢弃定位、地面物品管理。

全部为纯函数，不依赖 UI 层。
"""

from collections import deque
from core.grid import DIRS_8


# ═══════════════════════════════════════════════════
# 操作标签表（哈希表驱动，按 item_type + effect 查表）
# ═══════════════════════════════════════════════════

_EFFECT_LABELS: dict[str, str] = {
    "heal":         "饮用(治疗)",
    "restore_mp":   "饮用(回蓝)",
    "restore_food": "食用",
}

_TYPE_ACTIONS: dict[str, list[str]] = {
    "weapon": ["装备(左手)", "装备(右手)"],
    "armor":  ["装备"],
}

_TERMINAL_ACTIONS: list[str] = ["丢弃", "投掷"]


def get_item_actions(item) -> list[str]:
    """根据物品属性动态生成可用操作列表。

    哈希表驱动：按 item_type 查 _TYPE_ACTIONS，按 effect 查 _EFFECT_LABELS。
    不硬编码 isinstance 分支。

    Returns:
        操作标签列表，如 ["装备(左手)", "装备(右手)", "丢弃", "投掷"]
    """
    actions: list[str] = []

    # 按 item_type 查表
    item_type = getattr(item, 'item_type', 'misc')
    type_actions = _TYPE_ACTIONS.get(item_type, [])
    actions.extend(type_actions)

    # 消耗品：根据 effect 字段显示具体名称
    effect = getattr(item, 'effect', '')
    if effect:
        actions.append(_EFFECT_LABELS.get(effect, "使用"))
    elif getattr(item, 'food_restore', 0) > 0:
        # 可恢复饮食值但没有 effect 字段的物品（预留）
        actions.append("食用")

    # 所有物品通用操作
    actions.extend(_TERMINAL_ACTIONS)
    return actions


# ═══════════════════════════════════════════════════
# 地面物品管理
# ═══════════════════════════════════════════════════

MAX_TILE_SPACE = 10


def tile_space_used(ground_items: list, col: int, row: int) -> int:
    """计算指定格子上物品占据的总空间。"""
    total = 0
    for item, (ic, ir) in ground_items:
        if (ic, ir) == (col, row):
            total += item.space * item.count
    return total


def find_placeable_tile(ground_items: list, start_col: int, start_row: int,
                        item, map_width: int, map_height: int,
                        map=None, entities=None) -> tuple[int, int] | None:
    """从起点 BFS 查找第一个能放入物品的格子。

    起点通常为玩家位置，从相邻格开始由近到远搜索。
    BFS 跳过墙壁和活物所在的格子。

    Args:
        ground_items: 当前地上物品列表
        start_col, start_row: BFS 起点坐标
        item: 待放置的物品（需要 space 和 count 属性）
        map_width, map_height: 地图边界
        map: 地形网格（Grid[Terrain]），用于排除墙壁
        entities: 生物列表 [(Creature, (col, row))]，用于排除活物格

    Returns:
        (col, row) 或 None（无可用格子）
    """
    from core.movement import Terrain
    from core.combat.cover import is_full_cover

    needed = item.space * item.count
    visited: set[tuple[int, int]] = {(start_col, start_row)}
    queue: deque[tuple[int, int]] = deque()

    # 起点自身（玩家所在格）：可放物品（玩家站在物品上仍可交互）
    if tile_space_used(ground_items, start_col, start_row) + needed <= MAX_TILE_SPACE:
        return (start_col, start_row)

    # 将相邻格入队
    for dc, dr in DIRS_8:
        nc, nr = start_col + dc, start_row + dr
        if 0 <= nc < map_width and 0 <= nr < map_height:
            visited.add((nc, nr))
            queue.append((nc, nr))

    # BFS
    while queue:
        c, r = queue.popleft()

        # 跳过全身障碍
        if map and is_full_cover(map[c, r]):
            pass
        # 跳过活物格
        elif entities and any((ec, er) == (c, r) and c2.hp > 0 for c2, (ec, er) in entities):
            pass
        elif tile_space_used(ground_items, c, r) + needed <= MAX_TILE_SPACE:
            return (c, r)
        else:
            pass  # 空间不足，继续 BFS

        for dc, dr in DIRS_8:
            nc, nr = c + dc, r + dr
            if 0 <= nc < map_width and 0 <= nr < map_height and (nc, nr) not in visited:
                visited.add((nc, nr))
                queue.append((nc, nr))

    return None


def place_on_ground(ground_items: list, item, col: int, row: int) -> None:
    """将物品放置到地上指定格子。同名称同类型物品堆叠。

    Args:
        ground_items: 地上物品列表（原地修改）
        item: 待放置的物品
        col, row: 目标坐标
    """
    for existing, (ec, er) in ground_items:
        if (ec, er) == (col, row) and existing.name == item.name and existing.item_type == item.item_type:
            # 堆叠
            existing.count += item.count
            existing.weight += item.weight
            return
    # 新建条目
    ground_items.append((item, (col, row)))


def remove_from_inventory(player, item_index: int, quantity: int = 1):
    """从玩家背包扣除指定数量的物品。

    Args:
        player: Creature 对象
        item_index: 物品在 inventory 中的索引
        quantity: 要扣除的数量

    Returns:
        扣除的 Item 副本（ground-ready），失败返回 None
    """
    if item_index < 0 or item_index >= len(player.inventory):
        return None

    item = player.inventory[item_index]
    if quantity > item.count:
        return None

    unit_weight = item.weight / item.count if item.count > 0 else 0

    if quantity < item.count:
        # 部分扣除
        item.count -= quantity
        item.weight -= unit_weight * quantity
        # 创建扣除部分的副本
        return copy_item_with_count(item, quantity, unit_weight * quantity)
    else:
        # 全部扣除
        return player.inventory.pop(item_index)


def copy_item_with_count(item, count: int, weight: float):
    """创建物品副本，指定 count 和 weight。

    不依赖 isinstance，通过 item_type 和属性字典通用复制。
    """
    from core.entity import Item, Weapon, Armor

    item_type = getattr(item, 'item_type', 'misc')
    if item_type == "weapon":
        return Weapon(
            name=item.name, weapon_type=getattr(item, 'weapon_type', 'melee'),
            category=getattr(item, 'category', 'simple'),
            damage=getattr(item, 'damage', '1d4'),
            damage_type=getattr(item, 'damage_type', 'bludgeoning'),
            attack_stat=getattr(item, 'attack_stat', 'str'),
            ap_cost=getattr(item, 'ap_cost', 2),
            range_normal=getattr(item, 'range_normal', 0),
            range_max=getattr(item, 'range_max', 0),
            properties=list(getattr(item, 'properties', []) or []),
            weight=weight, price=dict(getattr(item, 'price', {}) or {}),
            description=getattr(item, 'description', ''),
            count=count, space=getattr(item, 'space', 1),
            loaded=getattr(item, 'loaded', True),
        )
    elif item_type == "armor":
        return Armor(
            name=item.name, armor_type=getattr(item, 'armor_type', 'light'),
            slot=getattr(item, 'slot', 'chest'),
            ac_bonus=getattr(item, 'ac_bonus', 0),
            tenacity_bonus=getattr(item, 'tenacity_bonus', 0),
            str_requirement=getattr(item, 'str_requirement', 8),
            weight=weight, price=dict(getattr(item, 'price', {}) or {}),
            description=getattr(item, 'description', ''),
            count=count, space=getattr(item, 'space', 1),
        )
    else:
        return Item(
            name=item.name, item_type=item_type,
            weight=weight, price=dict(getattr(item, 'price', {}) or {}),
            description=getattr(item, 'description', ''),
            effect=getattr(item, 'effect', ''),
            amount=getattr(item, 'amount', ''),
            ap_cost=getattr(item, 'ap_cost', 0),
            count=count, space=getattr(item, 'space', 1),
        )


# ═══════════════════════════════════════════════════
# 地上物品渲染辅助
# ═══════════════════════════════════════════════════

GROUND_ITEM_RENDER: dict[str, dict] = {
    "weapon":     {"char": "+", "color": "yellow"},
    "armor":      {"char": "+", "color": "cyan"},
    "consumable": {"char": "!", "color": "green"},
    "material":   {"char": "%", "color": "white"},
    "misc":       {"char": "?", "color": "#888888"},
}

_ITEM_TYPE_LABELS: dict[str, str] = {
    "weapon": "武器",
    "armor": "护甲",
    "consumable": "消耗",
    "material": "材料",
    "misc": "杂项",
}


def get_ground_items_at(ground_items: list, col: int, row: int) -> list:
    """返回指定格子上所有地上物品的渲染信息列表。

    Returns:
        list[dict]: [{"char": str, "color": str, "count": int, "item": Item}, ...]
    """
    result = []
    for item, (ic, ir) in ground_items:
        if (ic, ir) == (col, row):
            render_info = GROUND_ITEM_RENDER.get(item.item_type, GROUND_ITEM_RENDER["misc"])
            result.append({
                "char": render_info["char"],
                "color": render_info["color"],
                "count": item.count,
                "item": item,
                "item_type": item.item_type,
                "type": item.item_type,
                "space": getattr(item, 'space', 1),
                "name": item.name,
            })
    return result


# ═══════════════════════════════════════════════════
# 投掷范围计算
# ═══════════════════════════════════════════════════

def get_throw_range(item, vision_range: int = 8) -> int:
    """投掷正常射程：thrown(N/M) 取 N，裸 thrown 默认 4，否则 min(视野, 基础射程 - 重量修正)。"""
    props = getattr(item, 'properties', []) or []
    for p in props:
        if p.startswith('thrown'):
            if p == 'thrown':
                return 4  # 裸 thrown 默认正常射程 4
            if p.startswith('thrown('):
                # thrown(4/6) → 正常射程 4
                parts = p[7:-1].split('/')
                return int(parts[0])
    # 通用计算：基础射程 - 重量修正
    if hasattr(item, 'throw_range') and item.throw_range > 0:
        base = item.throw_range
    else:
        base = 3
    weight = getattr(item, 'weight', 0)
    base = base - int(weight)
    return max(1, min(vision_range, base))


def get_throw_max_range(item, normal_range: int) -> int:
    """返回投掷最大射程。thrown(N/M) 取 M，否则等于正常射程。"""
    props = getattr(item, 'properties', []) or []
    for p in props:
        if p.startswith('thrown('):
            parts = p[7:-1].split('/')
            if len(parts) >= 2:
                return int(parts[1])
    return normal_range
