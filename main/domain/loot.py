"""搜刮/物品入包 —— 背包堆叠逻辑（纯规则，无 UI）。"""

CURRENCY_FIELDS = ("gp", "sp", "cp")


def is_currency_entry(entry) -> bool:
    """loot 条目判定：含 gp/sp/cp 字段且无 name → 货币（直接入账，非物品）。

    审查报告7 决策：货币不是物品。loot 里的货币条目为纯字段（如 {"sp": 20}），
    物品条目才含 name。据此判定，替代旧代码里 name=="货币" 的字符串特判。
    """
    if not isinstance(entry, dict) or "name" in entry:
        return False
    return any(k in entry for k in CURRENCY_FIELDS)


def _add_to_inventory(player, item) -> None:
    """添加物品到背包，同名称同类型物品堆叠计数。"""
    for existing in player.inventory:
        if existing.name == item.name and existing.item_type == item.item_type:
            existing.count += item.count
            existing.weight += item.weight
            return
    player.inventory.append(item)
