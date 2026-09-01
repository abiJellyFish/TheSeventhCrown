"""交易系统 —— 商店加载、买卖逻辑、货币换算。

商店数据从 data/shops/<shop_id>.json 加载，每个商店独立一个文件。
物品价格从 data/items/*.json 查询，商店可覆盖（price_override）。

货币换算：1 GP = 10 SP = 100 CP
"""

import json
import os
from dataclasses import replace
from domain.entity import Item
from domain.items.factory import ItemFactory
from domain.ports import RepositoryPort, get_repository


_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SHOPS_DIR = os.path.join(_DATA_DIR, "shops")

# 商店默认库存量（stock_qty 未指定时使用）
DEFAULT_STOCK_QTY = 99


def load_item(item_name: str, repository: RepositoryPort | None = None) -> Item | None:
    """通过统一数据仓储创建物品实例。"""
    return ItemFactory.create_from_name(item_name, repository or get_repository())


def resolve_items(
    refs: list[dict],
    repository: RepositoryPort | None = None,
) -> list[Item]:
    """将名称引用列表解析为物品实例列表。

    refs: [{"name": "火把", "count": 1}, {"name": "治疗药水", "count": 3}]
    """
    repository = repository or get_repository()
    result = []
    for ref in refs:
        name = ref["name"]
        count = ref.get("count", 1)
        item = load_item(name, repository)
        if item is None:
            raise ValueError(f"resolve_items: 物品 '{name}' 未在 data/items/ 中定义")
        item.count = count
        if item.weight:
            item.weight = item.weight * count
        result.append(item)
    return result


# ── 货币换算 ──

def price_to_copper(price: dict) -> int:
    """将 {"gp": N, "sp": N, "cp": N} 转为铜币总值。"""
    gp = price.get("gp", 0)
    sp = price.get("sp", 0)
    cp = price.get("cp", 0)
    return gp * 100 + sp * 10 + cp


def copper_to_currency(cp_total: int) -> dict:
    """将铜币总值转为 gp/sp/cp 字典。"""
    cp_total = max(0, cp_total)
    gp = cp_total // 100
    remainder = cp_total % 100
    sp = remainder // 10
    cp = remainder % 10
    return {"gp": gp, "sp": sp, "cp": cp}


def player_wealth_copper(player) -> int:
    """玩家总财富（铜币）。"""
    return player.gp * 100 + player.sp * 10 + player.cp


def player_can_afford(player, price: dict) -> bool:
    """检查玩家是否买得起。"""
    return player_wealth_copper(player) >= price_to_copper(price)


def player_pay(player, price: dict) -> bool:
    """扣除货币，返回是否成功。"""
    if not player_can_afford(player, price):
        return False
    total = player_wealth_copper(player) - price_to_copper(price)
    c = copper_to_currency(total)
    player.gp, player.sp, player.cp = c["gp"], c["sp"], c["cp"]
    return True


def player_receive(player, price: dict) -> None:
    """获得货币。"""
    total = player_wealth_copper(player) + price_to_copper(price)
    c = copper_to_currency(total)
    player.gp, player.sp, player.cp = c["gp"], c["sp"], c["cp"]


def sell_price(price: dict) -> dict:
    """半价收购价（向下取整铜币）。"""
    return copper_to_currency(price_to_copper(price) // 2)


def price_to_text(price: dict) -> str:
    """价格转显示文本，自动归一化进位（如 50SP → 5GP 进位后显示 8GP）。"""
    normalized = copper_to_currency(price_to_copper(price))
    parts = []
    if normalized.get("gp", 0):
        parts.append(f"{normalized['gp']}GP")
    if normalized.get("sp", 0):
        parts.append(f"{normalized['sp']}SP")
    if normalized.get("cp", 0):
        parts.append(f"{normalized['cp']}CP")
    return " ".join(parts) if parts else "0CP"


# ── 物品副本创建 ──

def _copy_item(item) -> Item:
    """创建物品的独立副本（用于交易，避免引用同一对象）。组件化复制。"""
    return Item(
        name=item.name, item_type=item.item_type, weight=item.weight,
        price=dict(item.price), description=item.description, effect=item.effect,
        amount=item.amount, count=1,
        throw_range=item.throw_range, throw_str_req=item.throw_str_req,
        throw_damage=item.throw_damage, throw_damage_type=item.throw_damage_type,
        throw_effect=item.throw_effect, becomes=item.becomes,
        dc_check=dict(item.dc_check) if item.dc_check else None,
        render_char=item.render_char, render_color=item.render_color,
        weapon=replace(item.weapon) if item.weapon else None,
        armor=replace(item.armor) if item.armor else None,
        light=replace(item.light) if item.light else None,
    )


# ── 商店加载与持久化 ──

def load_shop(
    shop_id: str,
    repository: RepositoryPort | None = None,
) -> dict | None:
    """加载商店数据。返回 None 表示商店文件不存在。"""
    repository = repository or get_repository()
    data = repository.load_shop_data(shop_id)
    if data is None:
        return None
    # 解析库存：补全物品实例和价格、库存量
    resolved_stock = []
    for entry in data.get("stock", []):
        item = load_item(entry["item_key"], repository)
        if item is None:
            continue
        if "price_override" in entry and entry["price_override"] is not None:
            price = entry["price_override"]
        else:
            price = dict(item.price) if item.price else {}
        stock_qty = entry.get("stock_qty", DEFAULT_STOCK_QTY)
        resolved_stock.append({
            "item": item, "price": price, "item_key": entry["item_key"],
            "stock_qty": stock_qty,
        })
    data["_resolved_stock"] = resolved_stock
    return data


def _save_shop(shop_data: dict) -> None:
    """将商店库存写回 JSON 文件。只写 stock 列表，保留元数据字段。"""
    # 测试环境不写文件，避免污染数据
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    shop_id = shop_data.get("shop_id")
    if not shop_id:
        return
    path = os.path.join(_SHOPS_DIR, f"{shop_id}.json")
    # 从 _resolved_stock 构建持久化的 stock 列表
    stock_list = []
    for entry in shop_data.get("_resolved_stock", []):
        qty = entry.get("stock_qty", 0)
        if qty <= 0:
            continue
        stock_entry = {"item_key": entry["item_key"], "stock_qty": qty}
        # 保留原始 price_override（如果存在）
        orig_stock = shop_data.get("stock", [])
        for orig in orig_stock:
            if orig.get("item_key") == entry["item_key"]:
                if "price_override" in orig:
                    stock_entry["price_override"] = orig["price_override"]
                break
        stock_list.append(stock_entry)
    # 读取原文件保留元数据
    original = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            original = json.load(f)
    original["stock"] = stock_list
    original["shop_gold"] = shop_data.get("shop_gold", original.get("shop_gold", 0))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(original, f, ensure_ascii=False, indent=2)


def _find_stock_entry(shop_data: dict, item_key: str) -> dict | None:
    """在 _resolved_stock 中查找指定 item_key 的条目。"""
    for entry in shop_data.get("_resolved_stock", []):
        if entry["item_key"] == item_key:
            return entry
    return None


def _update_shop_stock_add(shop_data: dict, item) -> None:
    """向商店库存增加一个物品（出售时调用）。存在则 +qty，不存在则新增条目。"""
    item_key = item.name
    entry = _find_stock_entry(shop_data, item_key)
    if entry:
        entry["stock_qty"] = entry.get("stock_qty", 0) + 1
    else:
        new_entry = {
            "item": _copy_item(item),
            "price": dict(item.price) if item.price else {},
            "item_key": item_key,
            "stock_qty": 1,
        }
        shop_data.setdefault("_resolved_stock", []).append(new_entry)
        shop_data.setdefault("stock", []).append({"item_key": item_key, "stock_qty": 1})


def shop_gold_text(shop_data: dict) -> str:
    """商店资金显示文本。"""
    gold = shop_data.get("shop_gold", 0)
    return price_to_text(copper_to_currency(gold))


# ── 交易操作 ──

def trade_buy(player, shop_data: dict, stock_index: int) -> tuple[bool, str]:
    """玩家购买商店商品。返回 (成功, 日志消息)。"""
    stock = shop_data.get("_resolved_stock", [])
    if stock_index < 0 or stock_index >= len(stock):
        return False, "无效的商品序号"
    entry = stock[stock_index]
    if entry.get("stock_qty", 0) <= 0:
        return False, "该商品已售罄"
    price = entry["price"]
    if not player_can_afford(player, price):
        return False, f"金币不够，需要 {price_to_text(price)}"
    if not player_pay(player, price):
        return False, "扣款失败"
    # 创建物品副本加入背包
    new_item = _copy_item(entry["item"])
    player.inventory.append(new_item)
    # 扣减库存
    entry["stock_qty"] = entry.get("stock_qty", 1) - 1
    if entry["stock_qty"] <= 0:
        stock.pop(stock_index)
    _save_shop(shop_data)
    return True, f"买到了 {entry['item'].name}，花费 {price_to_text(price)}"


# ── 实体交易（P1 3.2：所有实体默认交易自身携带的物品）──

def build_creature_shop(creature) -> dict:
    """从实体自身物品栏构造商店数据（交易面板数据源，无 shop_id 的实体通用）。"""
    return {
        "name": creature.name,
        "shop_gold": creature.shop_gold,
        "creature": creature,
        "_resolved_stock": [
            {"item": it, "price": dict(it.price) if it.price else {},
             "item_key": it.name, "stock_qty": it.count}
            for it in creature.inventory
        ],
    }


def trade_buy_creature(player, creature, inv_index: int) -> tuple[bool, str]:
    """玩家购买实体携带的物品。返回 (成功, 日志消息)。"""
    inv = creature.inventory
    if inv_index < 0 or inv_index >= len(inv):
        return False, "无效的商品序号"
    item = inv[inv_index]
    price = dict(item.price) if item.price else {}
    if not player_can_afford(player, price):
        return False, f"金币不够，需要 {price_to_text(price)}"
    if not player_pay(player, price):
        return False, "扣款失败"
    new_item = _copy_item(item)
    new_item.count = 1
    player.inventory.append(new_item)
    if item.count > 1:
        unit_weight = item.weight / item.count
        item.count -= 1
        item.weight -= unit_weight
    else:
        inv.pop(inv_index)
    return True, f"买到了 {item.name}，花费 {price_to_text(price)}"


def trade_sell_creature(player, creature, inv_index: int) -> tuple[bool, str]:
    """玩家出售背包物品给实体。堆叠物品每次只卖 1 个。返回 (成功, 日志消息)。"""
    if inv_index < 0 or inv_index >= len(player.inventory):
        return False, "无效的背包序号"
    item = player.inventory[inv_index]
    price = sell_price(item.price)
    if price_to_copper(price) > creature.shop_gold:
        return False, "对方没有足够的钱收购这件物品"
    creature.shop_gold -= price_to_copper(price)
    player_receive(player, price)
    if item.count > 1:
        unit_weight = item.weight / item.count
        item.count -= 1
        item.weight -= unit_weight
    else:
        del player.inventory[inv_index]
    new_item = _copy_item(item)
    new_item.count = 1
    creature.inventory.append(new_item)
    return True, f"卖出了 {item.name}，获得 {price_to_text(price)}"


def trade_sell(player, shop_data: dict, inv_index: int) -> tuple[bool, str]:
    """玩家出售背包物品给商店。堆叠物品每次只卖 1 个。返回 (成功, 日志消息)。"""
    if inv_index < 0 or inv_index >= len(player.inventory):
        return False, "无效的背包序号"
    item = player.inventory[inv_index]
    price = sell_price(item.price)
    # 检查商店资金
    shop_gold = shop_data.get("shop_gold", 0)
    if price_to_copper(price) > shop_gold:
        shop_gp_text = price_to_text(copper_to_currency(shop_gold))
        return False, f"商人的钱不够收购这件物品 (仅有 {shop_gp_text})"
    # 商店扣款
    shop_data["shop_gold"] = shop_gold - price_to_copper(price)
    # 玩家收款
    player_receive(player, price)
    # 单件扣除：堆叠物品只减 1 个
    if item.count > 1:
        unit_weight = item.weight / item.count
        item.count -= 1
        item.weight -= unit_weight
    else:
        del player.inventory[inv_index]
    # 更新商店库存（新增或累加）
    _update_shop_stock_add(shop_data, item)
    _save_shop(shop_data)
    return True, f"卖出了 {item.name}，获得 {price_to_text(price)}"
