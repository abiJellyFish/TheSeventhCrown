"""交易系统 —— 商店加载、买卖逻辑、货币换算。

商店数据从 data/shops/<shop_id>.json 加载，每个商店独立一个文件。
物品价格从 data/items/*.json 查询，商店可覆盖（price_override）。

货币换算：1 GP = 10 SP = 100 CP
"""

import json
import os
from core.entity import Item, Weapon, Armor


_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_SHOPS_DIR = os.path.join(_DATA_DIR, "shops")

# 物品缓存：{name: dict}
_ITEM_CACHE: dict | None = None

# 商店默认库存量（stock_qty 未指定时使用）
DEFAULT_STOCK_QTY = 99


def _build_item_cache() -> dict:
    """构建物品名 → 原始数据字典 的缓存。"""
    global _ITEM_CACHE
    if _ITEM_CACHE is not None:
        return _ITEM_CACHE
    _ITEM_CACHE = {}
    items_dir = os.path.join(_DATA_DIR, "items")
    if not os.path.isdir(items_dir):
        return _ITEM_CACHE
    for filename in sorted(os.listdir(items_dir)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(items_dir, filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            name = entry.get("name")
            if name:
                _ITEM_CACHE[name] = entry
    return _ITEM_CACHE


def _load_item_by_key(item_key: str) -> Item | None:
    """从 data/items/*.json 加载单个物品实例。"""
    cache = _build_item_cache()
    data = cache.get(item_key)
    if data is None:
        return None
    if "weapon_type" in data:
        return Weapon.from_dict(data)
    if "armor_type" in data or "slot" in data:
        return Armor.from_dict(data)
    return Item.from_dict(data)


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
    """创建物品的独立副本（用于交易，避免引用同一对象）。"""
    if isinstance(item, Weapon):
        return Weapon.from_dict({
            "name": item.name, "weapon_type": item.weapon_type,
            "category": item.category, "damage": item.damage,
            "damage_type": item.damage_type, "attack_stat": item.attack_stat,
            "ap_cost": item.ap_cost, "range_normal": item.range_normal,
            "range_max": item.range_max,
            "properties": list(item.properties) if item.properties else [],
            "weight": item.weight, "price": dict(item.price),
            "description": item.description,
            "melee": dict(item.melee) if getattr(item, 'melee', None) else None,
        })
    elif isinstance(item, Armor):
        return Armor.from_dict({
            "name": item.name, "armor_type": item.armor_type,
            "slot": item.slot, "ac_bonus": item.ac_bonus,
            "tenacity_bonus": item.tenacity_bonus,
            "str_requirement": item.str_requirement,
            "weight": item.weight, "price": dict(item.price),
            "description": item.description,
        })
    else:
        return Item.from_dict({
            "name": item.name, "type": item.item_type,
            "effect": item.effect, "amount": item.amount,
            "ap_cost": item.ap_cost, "weight": item.weight,
            "price": dict(item.price),
            "description": item.description, "count": 1,
        })


# ── 商店加载与持久化 ──

def load_shop(shop_id: str) -> dict | None:
    """加载商店数据。返回 None 表示商店文件不存在。"""
    path = os.path.join(_SHOPS_DIR, f"{shop_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 解析库存：补全物品实例和价格、库存量
    resolved_stock = []
    for entry in data.get("stock", []):
        item = _load_item_by_key(entry["item_key"])
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
