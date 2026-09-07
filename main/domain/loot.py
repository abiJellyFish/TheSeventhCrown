"""搜刮/背包堆叠，货币与物品入账规则。"""

import domain.dice
from domain.items.item import item_type_key

CURRENCY_FIELDS = ("gp", "sp", "cp")
CURRENCY_LABELS = {"gp": "金币", "sp": "银币", "cp": "铜币"}
EQUIP_SLOTS = (
    "head", "chest", "arms", "legs", "left_hand", "right_hand", "spellbook",
)


def is_currency_entry(entry) -> bool:
    """loot 条目判定：含 gp/sp/cp 字段且无 name → 货币（直接入账，非物品）。

    审查报告7 决策：货币不是物品。loot 里的货币条目为纯字段（如 {"sp": 20}），
    物品条目才含 name。据此判定，替代旧代码里 name=="货币" 的字符串特判。
    """
    if not isinstance(entry, dict) or "name" in entry:
        return False
    return any(k in entry for k in CURRENCY_FIELDS)


def stack_key(item) -> tuple:
    """背包/地面堆叠键：同名同类型同品质同耐久才合并。"""
    return (
        item.name,
        item_type_key(item),
        getattr(item, "quality", "普通") or "",
        int(getattr(item, "durability", 0)),
        bool(getattr(item, "unfinished", False)),
        int(getattr(item, "craft_progress", 0)),
        getattr(item, "recipe_id", "") or "",
    )


def _add_to_inventory(player, item) -> None:
    """添加物品到背包，堆叠键相同则合并计数。"""
    key = stack_key(item)
    for existing in player.inventory:
        if stack_key(existing) == key:
            existing.count += item.count
            existing.weight += item.weight
            return
    player.inventory.append(item)


def obtained_label(item) -> str:
    """获得日志中的物品名：多份时在名称前加 x份。"""
    count = int(getattr(item, "count", 1) or 1)
    if count > 1:
        return f"{count}份{item.name}"
    return item.name


def grant_item(creature, item, state=None) -> str:
    """物品入账。日志用入账前的本次数量，避免堆叠后变成背包总数。"""
    message = f"{creature.name} 获得 {obtained_label(item)}"
    _add_to_inventory(creature, item)
    if state is not None:
        state.emit_log(message)
    return message


def create_loot_item(entry: dict):
    """根据 loot 条目创建物品实例。货币条目返回 None。"""
    if is_currency_entry(entry):
        return None
    name = entry.get("name", "")
    amount = entry.get("amount", 1)
    from domain.items.factory import ItemFactory
    from domain.ports import get_repository
    item = ItemFactory.create_from_name(name, get_repository())
    if item is None:
        from domain.items.item import Item
        item = Item(name=name, item_type="misc", count=amount, weight=0.1)
        return item
    item.count = amount
    item.weight *= amount
    return item


def _credit_currency(creature, entry: dict) -> None:
    for field in CURRENCY_FIELDS:
        amount = int(entry.get(field, 0) or 0)
        if amount:
            setattr(creature, field, getattr(creature, field, 0) + amount)


def ensure_loot_rolled(creature) -> int | None:
    """第一次搜刮时掷掉落表；之后直接返回 None。货币并入实体，物品进 loot_drops。"""
    if getattr(creature, "loot_rolled", False):
        return None
    roll = domain.dice.roll_2d6()
    loot_data = getattr(creature, "loot", None) or {}
    drops = list(getattr(creature, "loot_drops", None) or [])
    for entry in loot_data.get("always", []):
        if is_currency_entry(entry):
            _credit_currency(creature, entry)
            continue
        item = create_loot_item(entry)
        if item is not None:
            drops.append(item)
    for key, entries in loot_data.items():
        if not key.startswith("dc_"):
            continue
        dc = int(key.split("_")[1])
        if roll < dc:
            continue
        for entry in entries:
            if is_currency_entry(entry):
                _credit_currency(creature, entry)
                continue
            item = create_loot_item(entry)
            if item is not None:
                drops.append(item)
    creature.loot_drops = drops
    creature.loot_rolled = True
    return roll


def reset_loot_table(creature) -> None:
    """复活时重置掉落表；已被拿走的身上物品不恢复。"""
    creature.loot_rolled = False
    creature.loot_drops = []


def list_loot_entries(creature) -> list[dict]:
    """搜刮面板行：货币、掉落、装备、饰品、背包。id 在本次列表内稳定。"""
    entries = []
    for field in CURRENCY_FIELDS:
        amount = int(getattr(creature, field, 0) or 0)
        if amount <= 0:
            continue
        unit = field.upper()
        entries.append({
            "id": ("currency", field),
            "label": f"{CURRENCY_LABELS[field]} {amount}{unit}",
        })
    for item in list(getattr(creature, "loot_drops", None) or []):
        count = getattr(item, "count", 1)
        suffix = f" x{count}" if count > 1 else ""
        entries.append({
            "id": ("drop", id(item)),
            "label": f"{item.name}{suffix}",
            "item": item,
        })
    equipment = getattr(creature, "equipment", None) or {}
    for slot in EQUIP_SLOTS:
        item = equipment.get(slot)
        if item is None:
            continue
        entries.append({
            "id": ("eq", slot),
            "label": item.name,
            "item": item,
        })
    for item in list(getattr(creature, "accessories", None) or []):
        entries.append({
            "id": ("acc", id(item)),
            "label": item.name,
            "item": item,
        })
    for item in list(getattr(creature, "inventory", None) or []):
        count = getattr(item, "count", 1)
        suffix = f" x{count}" if count > 1 else ""
        entries.append({
            "id": ("inv", id(item)),
            "label": f"{item.name}{suffix}",
            "item": item,
        })
    return entries


def _take_item_to_player(player, item, state=None) -> str:
    return grant_item(player, item, state)


def take_loot_entries(creature, player, selected_ids, state=None) -> list[str]:
    """按勾选 id 从目标拿到玩家；返回已拿走的标签。来源侧对应减少。"""
    wanted = set(selected_ids)
    taken = []
    for entry in list_loot_entries(creature):
        eid = entry["id"]
        if eid not in wanted:
            continue
        kind = eid[0]
        if kind == "currency":
            field = eid[1]
            amount = int(getattr(creature, field, 0) or 0)
            if amount <= 0:
                continue
            from domain.trade import player_receive
            player_receive(player, {field: amount})
            setattr(creature, field, 0)
            taken.append(entry["label"])
            continue
        item = entry.get("item")
        if item is None:
            continue
        if kind == "drop":
            drops = list(getattr(creature, "loot_drops", None) or [])
            creature.loot_drops = [row for row in drops if row is not item]
            taken.append(_take_item_to_player(player, item, state))
        elif kind == "eq":
            slot = eid[1]
            if creature.equipment.get(slot) is not item:
                continue
            creature.equipment[slot] = None
            taken.append(_take_item_to_player(player, item, state))
        elif kind == "acc":
            creature.remove_accessory(item)
            taken.append(_take_item_to_player(player, item, state))
        elif kind == "inv":
            if item in creature.inventory:
                creature.inventory.remove(item)
                taken.append(_take_item_to_player(player, item, state))
            else:
                continue
        else:
            continue
    return taken
