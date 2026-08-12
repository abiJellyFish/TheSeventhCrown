"""交易系统 —— 货币换算、商店加载、买卖、堆叠出售、库存。"""
import pytest
from core.trade import (load_shop, trade_buy, trade_sell, copper_to_currency,
                         price_to_copper, price_to_text, player_can_afford,
                         sell_price)
from core.entity import Creature, Item


def _player(gp=10):
    p = Creature(name="测试", char_class="fighter", gp=gp)
    p.inventory = []
    return p

def _shop():
    return load_shop("merchant")


class TestCurrency:
    def test_price_to_copper(self):
        assert price_to_copper({"gp": 1, "sp": 5}) == 150

    def test_copper_to_currency(self):
        result = copper_to_currency(350)
        assert result["gp"] == 3 and result["sp"] == 5

    def test_half_price(self):
        assert price_to_copper({"gp": 2}) // 2 == 100

    def test_price_to_text_normalizes(self):
        """sp>=10 应进位到 gp，避免显示歧义。"""
        assert price_to_text({"gp": 3, "sp": 50}) == "8GP"
        assert price_to_text({"gp": 1, "sp": 5}) == "1GP 5SP"

    def test_sell_price_half(self):
        """半价收购向下取整。"""
        result = sell_price({"gp": 3, "sp": 5})
        assert result == {"gp": 1, "sp": 7, "cp": 5}  # 350//2 = 175 CP


class TestTrade:
    def test_load_merchant(self):
        shop = _shop()
        assert shop is not None
        assert len(shop["stock"]) > 0
        # 验证 stock_qty 被正确解析
        stock = shop["_resolved_stock"]
        assert stock[0]["stock_qty"] > 0

    def test_buy_success(self):
        p = _player(10)
        s = _shop()
        ok, msg = trade_buy(p, s, 0)
        assert ok is True
        assert len(p.inventory) == 1

    def test_buy_insufficient_gold(self):
        p = _player(0)
        s = _shop()
        ok, msg = trade_buy(p, s, 0)
        assert ok is False
        assert "金币不够" in msg

    def test_sell_single_from_stack(self):
        """堆叠物品每次只卖 1 个。"""
        p = _player(0)
        p.inventory.append(Item(name="浆果", item_type="consumable", weight=0.3,
                                 price={"cp": 2}, count=3))
        s = _shop()
        assert trade_sell(p, s, 0)[0]
        assert p.inventory[0].count == 2  # 3 → 2

    def test_sell_last_item_removes(self):
        """最后一个物品卖出后从背包移除。"""
        p = _player(0)
        p.inventory.append(Item(name="匕首", item_type="weapon", weight=0.5,
                                 price={"gp": 2}, count=1))
        s = _shop()
        assert trade_sell(p, s, 0)[0]
        assert len(p.inventory) == 0

    def test_sell_adds_to_shop_stock(self):
        """卖出商店没有的物品后，商店库存新增该物品。"""
        p = _player(0)
        p.inventory.append(Item(name="猪皮", item_type="material", weight=0.1,
                                 price={"sp": 4}, count=1))
        s = _shop()
        before = len(s["_resolved_stock"])
        assert trade_sell(p, s, 0)[0]
        after = len(s["_resolved_stock"])
        assert after == before + 1

    def test_buy_sell_roundtrip(self):
        p = _player(20)
        s = _shop()
        assert trade_buy(p, s, 0)[0]
        assert trade_sell(p, s, 0)[0]
