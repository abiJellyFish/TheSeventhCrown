"""物品操作 —— 物品操作菜单生成、丢弃定位、地面物品管理。

全部为纯函数，不依赖 UI 层。
"""

from collections import deque
from domain.grid import DIRS_8, PASSABLE_TERRAINS

MAX_TILE_SPACE = 0

def tile_space_used(ground_items: list, col: int, row: int) -> int:
    """兼容旧调用；物品不再以空间总量影响格子。"""
    return 0


# ═══════════════════════════════════════════════════
# 操作标签表（哈希表驱动，按 item_type + effect 查表）
# ═══════════════════════════════════════════════════

_EFFECT_LABELS: dict[str, str] = {
    "heal":         "饮用(治疗)",
    "restore_mp":   "饮用(回蓝)",
    "restore_food": "食用",
    "start_fire":   "点燃",
}

_TYPE_ACTIONS: dict[str, list[str]] = {
    "weapon":    ["装备(左手)", "装备(右手)"],
    "armor":     ["装备"],
    "accessory": ["穿戴"],
    "spellbook": ["持有"],
    "spell_scroll": ["施法"],
    "seed":      ["种植"],
}

_NAME_ACTIONS: dict[str, list[str]] = {
    "一瓶水":   ["倒水"],
    "空玻璃瓶": ["取水"],
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
    if getattr(item, "accessory", False) and "穿戴" not in type_actions:
        type_actions = ["穿戴"]
    actions.extend(type_actions)

    # 按物品名查表（取水、倒水等）
    name_actions = _NAME_ACTIONS.get(getattr(item, 'name', ''), [])
    actions.extend(name_actions)

    # 消耗品：根据 effect 字段显示具体名称
    effect = getattr(item, 'effect', '')
    if effect:
        actions.append(_EFFECT_LABELS.get(effect, "使用"))
    elif getattr(item, 'food_restore', 0) > 0:
        # 可恢复饮食值但没有 effect 字段的物品（预留）
        actions.append("食用")

    # 阅读文本物品（长老的提示等，P1 3.4）
    if getattr(item, 'read_text', ''):
        actions.append("阅读")

    # 所有物品通用操作
    actions.extend(_TERMINAL_ACTIONS)

    return actions


# ═══════════════════════════════════════════════════
# 地面物品管理
# ═══════════════════════════════════════════════════

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
        entities: 生物列表 [(Entity, (col, row))]，用于排除活物格

    Returns:
        (col, row) 或 None（无可用格子）
    """
    def can_place_at(col: int, row: int) -> bool:
        if map is not None and map[col, row] not in PASSABLE_TERRAINS:
            return False
        if any(
            position == (col, row)
            and getattr(
                getattr(item, "obstacle_type", None), "value",
                getattr(item, "obstacle_type", None),
            ) == "full"
            for item, position in ground_items
        ):
            return False
        if entities and any(position == (col, row) for _, position in entities):
            return False
        items = [existing for existing, position in ground_items
                 if position == (col, row)]
        if not items:
            return True
        return all(existing.name == item.name
                   and existing.item_type == item.item_type
                   and getattr(existing, "stack_limit", 99) > existing.count
                   for existing in items)

    visited: set[tuple[int, int]] = {(start_col, start_row)}
    queue: deque[tuple[int, int]] = deque()

    # 起点自身（玩家所在格）：可放物品（玩家站在物品上仍可交互）
    if can_place_at(start_col, start_row):
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

        if can_place_at(c, r):
            return (c, r)

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
    import copy
    occupied = {
        (existing.name, existing.item_type)
        for existing, position in ground_items
        if position == (col, row)
    }
    if occupied and (item.name, item.item_type) not in occupied:
        raise ValueError(f"地面物品不能同格：({col}, {row})")

    remaining = item.count
    unit_weight = item.weight / remaining if remaining else 0
    for existing, (ec, er) in ground_items:
        if ((ec, er) == (col, row) and existing.name == item.name
                and existing.item_type == item.item_type):
            capacity = max(0, getattr(existing, "stack_limit", 99) - existing.count)
            added = min(capacity, remaining)
            existing.count += added
            existing.weight += unit_weight * added
            remaining -= added
            if remaining == 0:
                return
    while remaining > 0:
        count = min(remaining, getattr(item, "stack_limit", 99))
        placed = copy.copy(item)
        placed.count = count
        placed.weight = unit_weight * count
        ground_items.append((placed, (col, row)))
        remaining -= count


def remove_from_inventory(player, item_index: int, quantity: int = 1):
    """从玩家背包扣除指定数量的物品。

    Args:
        player: Entity 对象
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

    数据驱动：用 dataclasses.replace 复制 Item，组件（weapon/armor/light）深拷贝，
    避免共享可变状态（loaded/properties/condition 等）。不依赖 isinstance 分派。
    """
    import copy as _copy
    from dataclasses import replace

    return replace(
        item,
        count=count,
        weight=weight,
        weapon=_copy.deepcopy(item.weapon) if item.weapon is not None else None,
        armor=_copy.deepcopy(item.armor) if item.armor is not None else None,
        light=_copy.deepcopy(item.light) if item.light is not None else None,
        spellbook=_copy.deepcopy(item.spellbook) if item.spellbook is not None else None,
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
    "spellbook":  {"char": "b", "color": "magenta"},
    "seed":       {"char": ",", "color": "rgb(255,160,160)"},
}

_ITEM_TYPE_LABELS: dict[str, str] = {
    "weapon": "武器",
    "armor": "护甲",
    "consumable": "消耗",
    "material": "材料",
    "misc": "杂项",
    "spellbook": "法术书",
}


def get_ground_items_at(ground_items: list, col: int, row: int) -> list:
    """返回指定格子上所有地上物品的渲染信息列表。

    Returns:
        list[dict]: [{"char": str, "color": str, "count": int, "item": Item}, ...]
    """
    result = []
    for item, (ic, ir) in ground_items:
        if (ic, ir) == (col, row):
            if (
                hasattr(item, "durability")
                and int(getattr(item, "durability", 0)) <= 0
            ):
                continue
            rc = getattr(item, 'render_char', '') or ""
            rcol = getattr(item, 'render_color', '') or ""
            if rc:
                render_info = {"char": rc, "color": rcol or "white"}
            else:
                render_info = GROUND_ITEM_RENDER.get(item.item_type, GROUND_ITEM_RENDER["misc"])
            result.append({
                "char": render_info["char"],
                "color": render_info["color"],
                "count": item.count,
                "item": item,
                "item_type": item.item_type,
                "type": item.item_type,
                "name": item.name,
                "description": item.description,
                "weight": item.weight,
                "durability": item.durability,
                "max_durability": item.max_durability,
                "obstacle_type": getattr(item.obstacle_type, "value", item.obstacle_type),
                "block_value": item.block_value,
                "stack_limit": item.stack_limit,
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
