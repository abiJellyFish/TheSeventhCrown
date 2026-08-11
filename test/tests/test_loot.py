"""搜刮系统测试 —— 2d6 检定、物品创建、货币入账。"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.entity import Player, Creature, Item, Weapon, Armor
from core.trade import player_receive, _build_item_cache, price_to_copper, price_to_text


class _FakeApp:
    """模拟 MVPApp 的最小上下文，用于测试搜刮方法。"""

    def __init__(self, player):
        self._state = _FakeState(player)
        self._act_log = _FakeLog()

    def _create_loot_item(self, entry: dict):
        """复制自 MVPApp._create_loot_item。"""
        name = entry.get("name", "")
        amount = entry.get("amount", 1)
        price = entry.get("price", None)

        if name == "货币" and price:
            player_receive(self._state.player, price)
            self._act_log.add(f"  获得: {price_to_text(price)}")
            return None

        item = self._load_item_by_name(name)
        if item is None:
            item = Item(name=name, item_type="misc", count=amount, weight=0.1)
        else:
            item.count = amount
        return item

    def _load_item_by_name(self, name: str):
        """模拟从缓存加载。"""
        cache = _build_item_cache()
        data = cache.get(name)
        if data is None:
            return None
        if "weapon_type" in data:
            return Weapon.from_dict(data)
        if "armor_type" in data or "slot" in data:
            return Armor.from_dict(data)
        return Item.from_dict(data)

    def _interact_loot(self, creature, roll_override=None) -> list:
        """模拟搜刮逻辑，返回获得的物品列表（None 表示货币已入账）。"""
        import random as _random

        if getattr(creature, '_looted', False):
            self._act_log.add("已经搜刮过了")
            return []

        creature._looted = True

        if roll_override is not None:
            roll = roll_override
        else:
            roll = _random.randint(1, 6) + _random.randint(1, 6)

        self._act_log.add(f"[搜刮] {creature.name}: 搜刮检定 2d6={roll}")

        loot_data = getattr(creature, 'loot', {}) or {}
        found = []

        for entry in loot_data.get("always", []):
            item = self._create_loot_item(entry)
            found.append(item)

        for key, entries in loot_data.items():
            if not key.startswith("dc_"):
                continue
            dc = int(key.split("_")[1])
            if roll >= dc:
                for entry in entries:
                    item = self._create_loot_item(entry)
                    found.append(item)

        if not found:
            self._act_log.add("  什么都没有找到...")

        return found


class _FakeState:
    def __init__(self, player):
        self.player = player


class _FakeLog:
    def __init__(self):
        self.messages = []

    def add(self, msg: str):
        self.messages.append(msg)


# ── helpers ──

def _make_player(gp=0, sp=0, cp=0):
    """创建测试用玩家。"""
    p = Player(name="测试玩家", char_class="fighter")
    p.gp, p.sp, p.cp = gp, sp, cp
    return p


def _make_creature(name="测试怪物", loot=None):
    """创建测试用生物。"""
    return Creature(
        name=name, faction="hostile",
        hp=10, max_hp=10,
        tenacity=5, max_tenacity=5,
        loot=loot or {},
    )


# ═══════════════════════════════════════ Tests ═══════════════════════════════════════


class TestLootItemCreation:
    """测试 _create_loot_item 方法。"""

    def test_currency_item_returns_none(self):
        """货币物品不返回 Item，直接入账。"""
        p = _make_player()
        app = _FakeApp(p)
        entry = {"name": "货币", "price": {"gp": 2}, "amount": 1}
        result = app._create_loot_item(entry)

        assert result is None
        assert p.gp == 2  # 初始 0 + 2
        assert p.sp == 0
        assert p.cp == 0

    def test_currency_item_sp(self):
        """SP 货币正确入账。"""
        p = _make_player()
        app = _FakeApp(p)
        entry = {"name": "货币", "price": {"sp": 20}, "amount": 1}
        result = app._create_loot_item(entry)

        assert result is None
        assert p.gp == 2  # 初始 0 + 2 (20SP = 2GP)
        assert p.cp == 0

    def test_normal_item_from_cache(self):
        """普通物品从缓存加载并设置数量。短棒在 items/weapons.json 中存在。"""
        p = _make_player()
        app = _FakeApp(p)
        entry = {"name": "短棒"}
        result = app._create_loot_item(entry)

        assert result is not None
        assert isinstance(result, Weapon)
        assert result.name == "短棒"
        assert result.count == 1

    def test_normal_item_with_amount(self):
        """设置 amount 后 count 正确。"""
        p = _make_player()
        app = _FakeApp(p)
        entry = {"name": "浆果", "amount": 3}
        result = app._create_loot_item(entry)

        assert result is not None
        assert isinstance(result, Item)
        assert result.name == "浆果"
        assert result.count == 3

    def test_fallback_item(self):
        """缓存未命中时创建简单 Item。"""
        p = _make_player()
        app = _FakeApp(p)
        entry = {"name": "不存在的物品", "amount": 1}
        result = app._create_loot_item(entry)

        assert result is not None
        assert isinstance(result, Item)
        assert result.name == "不存在的物品"
        assert result.item_type == "misc"
        assert result.count == 1


class TestLootDC:
    """测试 2d6 搜刮检定逻辑。"""

    def test_always_items_obtained(self):
        """always 物品无论 2d6 结果都获得。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {"always": [{"name": "浆果", "amount": 2}]}
        c = _make_creature(name="测试怪", loot=loot_data)

        found = app._interact_loot(c, roll_override=2)  # 最低值也获得

        assert len(found) == 1
        assert found[0].name == "浆果"
        assert found[0].count == 2

    def test_dc_check_pass(self):
        """2d6 >= DC 时获得 DC 物品。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {"dc_6": [{"name": "短棒"}]}
        c = _make_creature(name="测试怪", loot=loot_data)

        found = app._interact_loot(c, roll_override=8)  # 8 >= 6, pass

        assert len(found) == 1
        assert found[0].name == "短棒"

    def test_dc_check_equal(self):
        """2d6 == DC 时也获得（边界情况）。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {"dc_10": [{"name": "长剑"}]}
        c = _make_creature(name="测试怪", loot=loot_data)

        found = app._interact_loot(c, roll_override=10)  # 10 == 10, pass

        assert len(found) == 1
        assert found[0].name == "长剑"

    def test_dc_check_fail(self):
        """2d6 < DC 时不获得 DC 物品。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {"dc_10": [{"name": "长剑"}]}
        c = _make_creature(name="测试怪", loot=loot_data)

        found = app._interact_loot(c, roll_override=5)  # 5 < 10, fail

        assert len(found) == 0

    def test_multiple_dc_tiers(self):
        """多个 DC 层次，只获得达标的。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {
            "always": [{"name": "浆果", "amount": 1}],
            "dc_4": [{"name": "肋骨"}],
            "dc_8": [{"name": "短棒"}],
            "dc_12": [{"name": "长剑"}],
        }
        c = _make_creature(name="测试怪", loot=loot_data)

        found = app._interact_loot(c, roll_override=9)  # 9 >= dc_4 和 dc_8, < dc_12

        names = [f.name for f in found]
        assert "浆果" in names      # always
        assert "肋骨" in names      # dc_4 pass (9 >= 4)
        assert "短棒" in names      # dc_8 pass (9 >= 8)
        assert "长剑" not in names  # dc_12 fail (9 < 12)
        assert len(found) == 3

    def test_already_looted(self):
        """重复搜刮返回提示。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {"always": [{"name": "浆果", "amount": 1}]}
        c = _make_creature(name="测试怪", loot=loot_data)

        # 第一次搜刮
        found1 = app._interact_loot(c, roll_override=7)
        assert len(found1) == 1

        # 第二次搜刮
        found2 = app._interact_loot(c, roll_override=7)
        assert len(found2) == 0
        assert "已经搜刮过了" in app._act_log.messages[-1]

    def test_currency_and_items_mixed(self):
        """同时有货币和物品的 loot。"""
        p = _make_player()
        app = _FakeApp(p)
        loot_data = {
            "always": [
                {"name": "货币", "price": {"gp": 1}, "amount": 1},
                {"name": "浆果", "amount": 2},
            ],
        }
        c = _make_creature(name="测试怪", loot=loot_data)

        found = app._interact_loot(c, roll_override=7)

        # 货币项为 None，物品为浆果
        assert found == [None, found[1]]
        assert found[1] is not None
        assert found[1].name == "浆果"
        assert found[1].count == 2
        assert p.gp == 1  # 初始 0 + 1

    def test_empty_loot(self):
        """空 loot 不报错。"""
        p = _make_player()
        app = _FakeApp(p)
        c = _make_creature(name="测试怪", loot={})

        found = app._interact_loot(c, roll_override=7)
        assert found == []
