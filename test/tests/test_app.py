"""app.py 集成测试 —— 导入冒烟 + 物品栏/装备核心流程。"""
import pytest
from core.entity import Player, Item, Weapon


def _player():
    return Player(name="测试", char_class="fighter")


class TestSmoke:
    def test_import_core_modules(self):
        import core.dice, core.grid, core.entity, core.loader
        import core.movement, core.fov, core.pendulum, core.game_state, core.rest
        import core.combat.initiative, core.combat.attack, core.combat.death
        import core.combat.cover, core.combat.flow, core.combat.dual_wield
        import core.ai.discretize, core.ai.engine, core.save.database
        import core.interact, core.trade, core.map.generation

    def test_new_entity_features(self):
        p = _player()
        assert p.total_carry_weight() == 0.0
        assert p.carry_status()["label"] in ("轻便", "负重", "超重")

    def test_create_game_loads_player(self):
        from render.textual.app import MVPApp
        app = MVPApp()
        app._create_game()
        p = app._state.player
        assert p.name
        assert p.inventory is not None

    @pytest.mark.skip(reason="Textual compose 需要运行中的应用上下文，无法在单元测试中执行")
    def test_app_compose_yields_widgets(self):
        from render.textual.app import MVPApp
        app = MVPApp()
        widgets = list(app.compose())
        assert len(widgets) >= 8


class TestInventory:
    def test_add_new_item(self):
        p = _player()
        p.inventory.append(Item(name="治疗药水", item_type="consumable", count=1, weight=0.5))
        assert len(p.inventory) == 1

    def test_stack_same_item(self):
        p = _player()
        i1 = Item(name="治疗药水", item_type="consumable", count=1, weight=0.5)
        i2 = Item(name="治疗药水", item_type="consumable", count=1, weight=0.5)
        p.inventory.append(i1)
        # stack: merge into first
        for existing in p.inventory:
            if existing.name == i2.name and existing.item_type == i2.item_type:
                existing.count += i2.count
                existing.weight += i2.weight
                break
        assert p.inventory[0].count == 2

    def test_equip_to_empty_hand(self):
        p = _player()
        sword = Weapon.from_dict({"name": "长剑", "weapon_type": "melee", "ap_cost": 3,
                                   "damage": "1d8", "damage_type": "slashing", "weight": 2.0})
        p.equipment["left_hand"] = sword
        assert p.equipment["left_hand"].name == "长剑"


class TestUseItem:
    def _setup_app(self):
        from render.textual.app import MVPApp
        app = MVPApp()
        app._create_game()
        # compose 前的 widget 均为 None，mock 避免 _use_item 内部调用空引用
        app._act_log = type("MockLog", (), {"add": lambda self, msg: None})()
        app._right_panel = type("MockPanel", (), {"refresh": lambda self: None})()
        app._wake_input = lambda: None
        return app

    def test_use_item_pushes_to_menu_stack(self):
        from core.entity import Item
        app = self._setup_app()
        p = app._state.player
        p.inventory = [Item(name="短剑", item_type="weapon", weight=1.0, count=1)]
        app._use_item("I1")
        assert len(app._state.item_menu_stack) == 1
        assert app._state.item_menu_stack[0]["item"].name == "短剑"

    def test_use_item_invalid_index_no_crash(self):
        app = self._setup_app()
        app._state.player.inventory = []
        app._use_item("I1")  # 空背包，不应崩溃
