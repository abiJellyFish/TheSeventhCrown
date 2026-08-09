"""交易系统测试 —— 货币换算、商店加载、买卖逻辑。"""

import os
import pytest
from core.entity import Player, Item, Weapon, Armor
from core.trade import (
    price_to_copper, copper_to_currency,
    player_wealth_copper, player_can_afford,
    player_pay, player_receive, sell_price, price_to_text,
    load_shop, trade_buy, trade_sell, shop_gold_text,
)


# ═══════════════════════════════════
# 货币换算
# ═══════════════════════════════════

class TestCurrency:

    def test_price_to_copper_gp_only(self):
        assert price_to_copper({"gp": 3}) == 300

    def test_price_to_copper_sp_only(self):
        assert price_to_copper({"sp": 50}) == 500

    def test_price_to_copper_cp_only(self):
        assert price_to_copper({"cp": 25}) == 25

    def test_price_to_copper_mixed(self):
        # 3 GP = 300 CP, 50 SP = 500 CP → 800 CP
        assert price_to_copper({"gp": 3, "sp": 50}) == 800

    def test_price_to_copper_empty(self):
        assert price_to_copper({}) == 0

    def test_copper_to_currency_gp(self):
        result = copper_to_currency(350)
        assert result == {"gp": 3, "sp": 5, "cp": 0}

    def test_copper_to_currency_only_sp(self):
        result = copper_to_currency(50)
        assert result == {"gp": 0, "sp": 5, "cp": 0}

    def test_copper_to_currency_only_cp(self):
        result = copper_to_currency(7)
        assert result == {"gp": 0, "sp": 0, "cp": 7}

    def test_copper_to_currency_zero(self):
        result = copper_to_currency(0)
        assert result == {"gp": 0, "sp": 0, "cp": 0}

    def test_copper_to_currency_negative_clamped(self):
        result = copper_to_currency(-100)
        assert result == {"gp": 0, "sp": 0, "cp": 0}

    def test_price_to_text(self):
        assert price_to_text({"gp": 3, "sp": 50}) == "3GP 50SP"
        assert price_to_text({"cp": 50}) == "50CP"
        assert price_to_text({"gp": 0, "sp": 0, "cp": 0}) == "0CP"

    def test_roundtrip(self):
        """copper_to_currency(price_to_copper(...)) 保持铜币值不变。"""
        for price in [{"gp": 3}, {"sp": 50}, {"gp": 3, "sp": 50}, {"cp": 25}]:
            copper = price_to_copper(price)
            back = copper_to_currency(copper)
            assert price_to_copper(back) == copper


# ═══════════════════════════════════
# 玩家货币操作
# ═══════════════════════════════════

def _make_player(gp=3, sp=0, cp=0):
    p = Player(name="测试", char_class="fighter")
    p.gp, p.sp, p.cp = gp, sp, cp
    return p


class TestPlayerMoney:

    def test_wealth_copper(self):
        p = _make_player(gp=3, sp=50)
        assert player_wealth_copper(p) == 800  # 300 + 500

    def test_can_afford_true(self):
        p = _make_player(gp=5)
        assert player_can_afford(p, {"gp": 3}) is True

    def test_can_afford_false(self):
        p = _make_player(gp=1)
        assert player_can_afford(p, {"gp": 3}) is False

    def test_can_afford_exact(self):
        p = _make_player(gp=3, sp=50)
        assert player_can_afford(p, {"gp": 3, "sp": 50}) is True

    def test_pay_success(self):
        p = _make_player(gp=10)
        result = player_pay(p, {"gp": 2, "sp": 50})  # 2GP 50SP = 700 CP
        assert result is True
        # 10 GP = 1000 CP, -700 = 300 CP = 3 GP
        assert p.gp == 3
        assert p.sp == 0
        assert p.cp == 0

    def test_pay_insufficient(self):
        p = _make_player(gp=1)
        result = player_pay(p, {"gp": 3})
        assert result is False
        assert p.gp == 1  # 未扣款

    def test_receive(self):
        p = _make_player(gp=1)
        player_receive(p, {"gp": 2, "sp": 50})  # +700 CP
        # 1 GP = 100 CP, +700 = 800 CP = 8 GP
        assert p.gp == 8
        assert p.sp == 0

    def test_pay_and_receive_combined(self):
        """支付后再收款，总额正确。"""
        p = _make_player(gp=10)
        assert player_pay(p, {"gp": 3})
        player_receive(p, {"gp": 1, "sp": 50})
        assert player_wealth_copper(p) == price_to_copper({"gp": 8, "sp": 50})


# ═══════════════════════════════════
# 收购价格
# ═══════════════════════════════════

class TestSellPrice:

    def test_half_price_even(self):
        price = sell_price({"gp": 4})
        assert price_to_copper(price) == 200  # 400 // 2

    def test_half_price_odd(self):
        """奇数铜币向下取整。"""
        price = sell_price({"cp": 5})
        assert price_to_copper(price) == 2  # 5 // 2

    def test_half_price_one_copper(self):
        """1 CP 半价 = 0 CP。"""
        price = sell_price({"cp": 1})
        assert price_to_copper(price) == 0


# ═══════════════════════════════════
# 商店加载
# ═══════════════════════════════════

class TestLoadShop:

    def test_load_merchant(self):
        shop = load_shop("merchant")
        assert shop is not None
        assert shop["name"] == "旅行商人"
        assert shop["shop_gold"] == 5000
        stock = shop["_resolved_stock"]
        assert len(stock) == 7
        # 验证每件商品都有 item 和 price
        for entry in stock:
            assert entry["item"] is not None
            assert "price" in entry
            assert "item_key" in entry

    def test_load_nonexistent_shop(self):
        shop = load_shop("nonexistent_shop_12345")
        assert shop is None

    def test_shop_gold_text(self):
        shop = load_shop("merchant")
        text = shop_gold_text(shop)
        assert "GP" in text or "SP" in text or "CP" in text


# ═══════════════════════════════════
# 买卖操作
# ═══════════════════════════════════

class TestTradeBuy:

    def test_buy_success(self):
        """购买成功：扣款 + 物品进背包。"""
        p = _make_player(gp=10)
        shop = load_shop("merchant")
        initial_inv = len(p.inventory)
        ok, msg = trade_buy(p, shop, 0)  # 长剑 3GP 50SP = 800 CP
        assert ok is True
        assert "买到" in msg or "买到了" in msg
        assert len(p.inventory) == initial_inv + 1
        # 10 GP = 1000 CP, -800 = 200 CP = 2 GP
        assert p.gp == 2
        assert p.sp == 0

    def test_buy_insufficient_funds(self):
        """余额不足 → 购买失败，背包不变。"""
        p = _make_player(gp=0)
        shop = load_shop("merchant")
        initial_inv = len(p.inventory)
        ok, msg = trade_buy(p, shop, 0)
        assert ok is False
        assert "不够" in msg or "金币不够" in msg
        assert len(p.inventory) == initial_inv

    def test_buy_invalid_index(self):
        """无效序号 → 失败。"""
        p = _make_player(gp=10)
        shop = load_shop("merchant")
        ok, msg = trade_buy(p, shop, 999)
        assert ok is False

    def test_buy_multiple_items(self):
        """连续购买多件商品。"""
        p = _make_player(gp=20)
        shop = load_shop("merchant")
        ok1, _ = trade_buy(p, shop, 0)  # 长剑
        ok2, _ = trade_buy(p, shop, 1)  # 短弓
        assert ok1 and ok2
        assert len(p.inventory) == 2


class TestTradeSell:

    def test_sell_success(self):
        """出售成功：物品移出背包，半价收款。"""
        p = _make_player(gp=3)
        # 先买一件物品再卖掉
        shop = load_shop("merchant")
        trade_buy(p, shop, 5)  # 一包口粮 50CP
        inv_count = len(p.inventory)
        initial_wealth = player_wealth_copper(p)
        ok, msg = trade_sell(p, shop, inv_count - 1)
        assert ok is True
        assert "卖出" in msg or "卖出了" in msg
        assert len(p.inventory) == inv_count - 1
        # 收款半价：口粮价格 50CP，半价 = 25CP
        assert player_wealth_copper(p) == initial_wealth + 25

    def test_sell_merchant_broke(self):
        """商店资金不足 → 出售失败。"""
        p = _make_player(gp=10)
        shop = load_shop("merchant")
        # 把商店资金榨干
        shop["shop_gold"] = 0
        # 先买一件物品
        trade_buy(p, shop, 6)  # 一包草药 10SP = 100CP
        inv_count = len(p.inventory)
        ok, msg = trade_sell(p, shop, inv_count - 1)
        assert ok is False
        assert "不够" in msg or "钱不够" in msg
        # 物品仍在背包
        assert len(p.inventory) == inv_count

    def test_sell_invalid_index(self):
        """无效序号 → 出售失败。"""
        p = _make_player(gp=10)
        shop = load_shop("merchant")
        ok, msg = trade_sell(p, shop, 999)
        assert ok is False

    def test_sell_empty_inventory(self):
        """空背包 → 出售失败。"""
        p = _make_player(gp=10)
        p.inventory = []
        shop = load_shop("merchant")
        ok, msg = trade_sell(p, shop, 0)
        assert ok is False

    def test_sell_updates_shop_gold(self):
        """出售后商店资金减少。"""
        p = _make_player(gp=10)
        shop = load_shop("merchant")
        trade_buy(p, shop, 6)  # 一包草药
        initial_shop_gold = shop["shop_gold"]
        inv_count = len(p.inventory)
        trade_sell(p, shop, inv_count - 1)
        # 商店资金应减少（半价收购付款）
        assert shop["shop_gold"] < initial_shop_gold


# ═══════════════════════════════════
# 集成测试
# ═══════════════════════════════════

class TestTradeIntegration:

    def test_buy_sell_roundtrip(self):
        """购买后原价买入、半价卖出，玩家净亏损半价。"""
        p = _make_player(gp=10)
        shop = load_shop("merchant")
        initial_wealth = player_wealth_copper(p)  # 1000 CP
        # 购买长剑 3GP 50SP = 800 CP
        trade_buy(p, shop, 0)
        inv_idx = len(p.inventory) - 1
        # 卖掉（半价 = 400 CP）
        trade_sell(p, shop, inv_idx)
        final_wealth = player_wealth_copper(p)
        loss = initial_wealth - final_wealth
        # 净亏损 = 半价 = 800/2 = 400 CP = 4 GP
        assert loss == 400

    def test_multiple_shops_independent(self):
        """不同商店独立运作。"""
        shop1 = load_shop("merchant")
        shop2 = load_shop("merchant")  # 同一文件但不同实例
        assert shop1 is not shop2  # 每次加载新实例
        # 修改 shop1 不影响 shop2（运行时可修改数据）
        shop1["shop_gold"] -= 100
        assert shop2["shop_gold"] == 5000
