"""交互控制器 —— 拾取/宝箱/搜刮/采摘/休息/取水/门/入口/交易/对话/尸体/烹饪。"""
import json
import os
import random
from core.game_state import GameState
from core.entity import Entity, Weapon, are_hostile
import core.entity as ent
from core.movement import Terrain, find_path
from core.fov import LightLevel, compute_fov
from core.combat.initiative import roll_initiative
from core.combat.attack import (hit_check, roll_damage, reduce_tenacity,
    apply_damage_type_modifiers, parse_dice, roll_dice, resolve_attack,
    miss_message, cover_message, normalize_damage_type)
from core.combat.flow import CombatFlow
from core.map.generation import build_world, build_dungeon
from core.dice import roll_d20, check_dc, roll_2d6
from core.ai.engine import BehaviorEngine
from core.rest import short_rest, long_rest
from core.loader import DataLoader, _load_dialogues, _load_scene_actions
from core.save.database import SaveManager
from core.interact import InteractType, scan_interact_targets
from core.trade import (load_shop, trade_buy, trade_sell, price_to_text,
    copper_to_currency, shop_gold_text, player_receive, _build_item_cache,
    resolve_items, _load_item_by_key)
from core.item_actions import (get_item_actions, find_placeable_tile,
    place_on_ground, remove_from_inventory as item_remove_from_inventory,
    copy_item_with_count, get_throw_range, get_throw_max_range,
    tile_space_used, MAX_TILE_SPACE)
from core.loot import _add_to_inventory, is_currency_entry
from render.textual.fov import _update_fov


_ai_engine = BehaviorEngine()

_INTERACT_DISPATCH = {
    InteractType.TALK: "_interact_talk",
    InteractType.LOOT: "_interact_loot",
    InteractType.CORPSE: "_interact_corpse",
    InteractType.PICK: "_interact_pick",
    InteractType.REST: "_interact_rest",
    InteractType.OPEN: "_interact_door",
    InteractType.ENTER: "_interact_entrance",
    InteractType.PICKUP: "_interact_pickup",
    InteractType.CHEST: "_interact_chest",
    InteractType.FETCH_WATER: "_interact_fetch_water",
}

RECIPES = {
    "一磅野猪肉": {"result": "烤兽肉", "time": 1},
    "浆果": {"result": "烤熟的浆果", "time": 1},
}


class InteractMixin:

    # ── 捡起交互 ──

    def _interact_pickup(self, target) -> None:
        """捡起地上物品。"""
        pos = target.pos
        items_at = target.extra.get("items", [])
        if not items_at:
            return

        if len(items_at) == 1 and items_at[0].count == 1:
            # 单物品直接捡起
            self._exec_pickup(items_at[0], pos, 1)
            self._cancel_interact()
            return

        # 多个物品或堆叠 → 选择捡哪个
        # 当前简化：捡第一个物品，有堆叠则进入数量选择
        first_item = items_at[0]
        if first_item.count > 1:
            self._state.item_menu_stack.append({
                "type": "pickup_quantity",
                "item": first_item,
                "pos": pos,
            })
        else:
            self._exec_pickup(first_item, pos, 1)
            self._cancel_interact()
        self.refresh_all()

    def _interact_chest(self, target) -> None:
        """打开箱子交互面板。"""
        pos = target.pos
        chest_data = target.extra.get("chest_data", {})
        if not chest_data:
            return
        self._state.interact_target = target
        self._state.interact_phase = "chest"
        self._act_log.add(f"打开了 {chest_data.get('label', '箱子')} — :C序号 拿取 :S序号 存放 [0] 离开")
        self._wake_input()
        self.refresh_all()

    def _handle_chest_take(self, cmd: str) -> None:
        """从箱子拿取物品到背包（含 GP 转移）。"""
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :C序号  如 :C1 拿取第1个物品")
            return

        target = getattr(self._state, 'interact_target', None)
        if target is None:
            return
        chest_data = target.extra.get("chest_data", {})
        chest_inv = chest_data.get("inventory", [])

        if num < 1 or num > len(chest_inv):
            self._act_log.add("序号无效")
            return

        item = chest_inv[num - 1]
        item_count = getattr(item, 'count', 1)

        # count > 1 → 进入数量选择
        if item_count > 1:
            target.extra["_qty_item"] = item
            target.extra["_qty_max"] = item_count
            target.extra["_qty_index"] = num - 1
            self._state.interact_phase = "chest_take_qty"
            self._act_log.add(f"拿取 {item.name} — 输入 :C数量  (1-{item_count})")
            self.refresh_all()
            return

        # count == 1 → 直接转移
        chest_inv.pop(num - 1)
        _add_to_inventory(self._state.player, item)
        self._act_log.add(f"拿取了 {item.name}")

        # 箱子清空时自动转移金币
        if not chest_inv:
            gp = chest_data.get("gp", 0)
            if gp > 0:
                self._state.player.gp += gp
                chest_data["gp"] = 0
                self._act_log.add(f"拿取了 {gp} GP")

        self.refresh_all()

    def _handle_chest_store(self, cmd: str) -> None:
        """从背包存放物品到箱子。"""
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :S序号  如 :S1 存放第1个物品")
            return

        target = getattr(self._state, 'interact_target', None)
        if target is None:
            return
        chest_data = target.extra.get("chest_data", {})
        chest_inv = chest_data.get("inventory", [])
        player_inv = self._state.player.inventory

        if num < 1 or num > len(player_inv):
            self._act_log.add("序号无效")
            return

        item = player_inv[num - 1]
        item_count = getattr(item, 'count', 1)

        # count > 1 → 进入数量选择
        if item_count > 1:
            target.extra["_qty_item"] = item
            target.extra["_qty_max"] = item_count
            target.extra["_qty_index"] = num - 1
            self._state.interact_phase = "chest_store_qty"
            self._act_log.add(f"存放 {item.name} — 输入 :S数量  (1-{item_count})")
            self.refresh_all()
            return

        # count == 1 → 直接转移
        player_inv.pop(num - 1)
        chest_inv.append(item)
        self._act_log.add(f"存放了 {item.name}")
        self.refresh_all()

    def _handle_chest_take_qty(self, cmd: str) -> None:
        """拿取数量选择。"""
        if cmd == "0":
            self._state.interact_phase = "chest"
            self.refresh_all()
            return

        try:
            qty = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :C数量  如 :C3 拿取3个")
            return

        target = getattr(self._state, 'interact_target', None)
        if target is None:
            return
        chest_data = target.extra.get("chest_data", {})
        chest_inv = chest_data.get("inventory", [])
        extra = target.extra
        item = extra.get("_qty_item")
        max_qty = extra.get("_qty_max", 1)
        idx = extra.get("_qty_index", 0)

        if item is None or qty < 1 or qty > max_qty:
            self._act_log.add(f"数量无效 (1-{max_qty})")
            return

        if qty >= max_qty:
            # 全量转移
            chest_inv.pop(idx)
            _add_to_inventory(self._state.player, item)
            self._act_log.add(f"拿取了 {item.name} x{max_qty}")
        else:
            # 部分转移
            from core.item_actions import copy_item_with_count
            unit_w = item.weight / item.count if item.count > 0 else 0
            split = copy_item_with_count(item, qty, unit_w * qty)
            item.count -= qty
            item.weight -= split.weight
            _add_to_inventory(self._state.player, split)
            self._act_log.add(f"拿取了 {split.name} x{qty}")

        # 箱子清空时自动转移金币
        if not chest_inv:
            gp = chest_data.get("gp", 0)
            if gp > 0:
                self._state.player.gp += gp
                chest_data["gp"] = 0
                self._act_log.add(f"拿取了 {gp} GP")

        # 清理临时字段
        for k in ("_qty_item", "_qty_max", "_qty_index"):
            extra.pop(k, None)
        self._state.interact_phase = "chest"
        self.refresh_all()

    def _handle_chest_store_qty(self, cmd: str) -> None:
        """存放数量选择。"""
        if cmd == "0":
            self._state.interact_phase = "chest"
            self.refresh_all()
            return

        try:
            qty = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :S数量  如 :S3 存放3个")
            return

        target = getattr(self._state, 'interact_target', None)
        if target is None:
            return
        chest_data = target.extra.get("chest_data", {})
        chest_inv = chest_data.get("inventory", [])
        player_inv = self._state.player.inventory
        extra = target.extra
        item = extra.get("_qty_item")
        max_qty = extra.get("_qty_max", 1)

        if item is None or qty < 1 or qty > max_qty:
            self._act_log.add(f"数量无效 (1-{max_qty})")
            return

        if qty >= max_qty:
            # 全量转移
            # 从背包找到并移除（索引可能因其他操作变化，重新查找）
            for i, inv_item in enumerate(player_inv):
                if inv_item is item:
                    player_inv.pop(i)
                    break
            chest_inv.append(item)
            self._act_log.add(f"存放了 {item.name} x{max_qty}")
        else:
            # 部分转移
            from core.item_actions import copy_item_with_count
            unit_w = item.weight / item.count if item.count > 0 else 0
            split = copy_item_with_count(item, qty, unit_w * qty)
            item.count -= qty
            item.weight -= split.weight
            chest_inv.append(split)
            self._act_log.add(f"存放了 {split.name} x{qty}")

        # 清理临时字段
        for k in ("_qty_item", "_qty_max", "_qty_index"):
            extra.pop(k, None)
        self._state.interact_phase = "chest"
        self.refresh_all()

    # ── Movement ──


    # ── Interact（重构）──

    def _cancel_interact(self) -> None:
        """取消交互，恢复默认状态。"""
        self._state.interact_phase = ""
        self._state.interact_targets = []
        self._state.interact_target = None
        self._state.shop_data = None
        self._state.item_menu_stack.clear()
        self._state.shove_target = None
        _update_fov(self._state)
        self._refresh_scene()
        self.refresh_all()


    def _dispatch_interact(self, target) -> None:
        """哈希表分发交互。"""
        method_name = _INTERACT_DISPATCH.get(target.interact_type)
        if method_name:
            getattr(self, method_name)(target)

    def _handle_interact_menu_select(self, num: int) -> None:
        """交互菜单选择（数字 0~N）。"""
        targets = self._state.interact_targets
        if num == 0:
            self._state.interact_phase = ""
            self._state.interact_targets = []
            self._state.interact_target = None
            self.refresh_all()
            return
        if 1 <= num <= len(targets):
            self._state.interact_phase = ""
            self._dispatch_interact(targets[num - 1])

    # ── 各交互类型处理方法 ──

    def _interact_talk(self, target) -> None:
        """与生物交谈。敌对生物直接开战。"""
        c = target.creature
        if c is None:
            return
        if are_hostile(c, self._state.player):
            self._act_log.add(f"{self._pn} 拔剑冲向 {c.name}!")
            self._start_combat(c)
            return
        self._state.interact_target = target
        self._state.interact_phase = "talking"
        self._act_log.add(f"{self._pn} 向 {c.name} 搭话")
        self._act_log.add(self._get_npc_dialogue(c))
        self.refresh_all()

    def _interact_corpse(self, target) -> None:
        """尸体面板：搜刮 / 捡起 二选一（尸体=每生物武器物品）。"""
        c = target.creature
        if c is None:
            return
        self._state.interact_target = target
        self._state.interact_phase = "corpse"
        self._act_log.add(f"面对 {c.name} 的尸体 — [1]搜刮 [2]捡起 [0]离开")
        self.refresh_all()

    def _corpse_loot(self) -> None:
        """尸体面板 [1]搜刮：复用原搜刮逻辑。"""
        target = getattr(self._state, 'interact_target', None)
        if target is None:
            return
        self._interact_loot(target)
        self._state.interact_phase = ""

    def _corpse_pickup(self) -> None:
        """尸体面板 [2]捡起：生成尸体武器 → 装备双手 → 移除尸体实体。"""
        target = getattr(self._state, 'interact_target', None)
        if target is None or target.creature is None:
            return
        c = target.creature
        corpse_weapon = getattr(c, 'corpse', None)
        if corpse_weapon is None:
            self._act_log.add(f"{c.name} 的尸体无法当作武器使用")
            self._state.interact_phase = ""
            self.refresh_all()
            return
        # 复制一份武器（避免共享模板实例），装备到双手（自动卸除原武器进背包）
        import copy as _copy
        weapon = _copy.deepcopy(corpse_weapon)
        weapon.count = 1
        self._equip_to_hand(weapon)
        self._act_log.add(f"{self._pn} 捡起了 {weapon.name} 并双手握持")
        # 移除尸体实体
        self._state.entities = [
            (cc, pp) for cc, pp in self._state.entities if cc is not c
        ]
        self._state._clean_entity_stealth(c)
        self._state.interact_phase = ""
        self.refresh_all()

    def _interact_loot(self, target) -> None:
        c = target.creature
        if c is None:
            return
        if getattr(c, '_looted', False):
            self._act_log.add("已经搜刮过了")
            self._state.interact_phase = ""
            self.refresh_all()
            return
        c._looted = True

        roll = roll_2d6()
        self._act_log.add(f"[搜刮] {c.name}: 搜刮检定 2d6={roll}")

        loot_data = getattr(c, 'loot', {}) or {}
        found = []

        # always 物品直接获得
        for entry in loot_data.get("always", []):
            item = self._create_loot_item(entry)
            found.append(item)

        # DC 物品：2d6 >= DC 才获得
        for key, entries in loot_data.items():
            if not key.startswith("dc_"):
                continue
            dc = int(key.split("_")[1])
            if roll >= dc:
                for entry in entries:
                    item = self._create_loot_item(entry)
                    found.append(item)

        if found:
            for item in found:
                if item is not None:
                    _add_to_inventory(self._state.player, item)
                    self._act_log.add(f"  获得: {item.name}" + (f" x{item.count}" if item.count > 1 else ""))
        else:
            self._act_log.add("  什么都没有找到...")
        self.refresh_all()

    def _create_loot_item(self, entry: dict):
        """根据 loot 条目创建物品实例。货币条目直接入账，返回 None。"""
        # 货币条目：直接入账（含 gp/sp/cp 且无 name）
        if is_currency_entry(entry):
            player_receive(self._state.player, entry)
            self._act_log.add(f"  获得: {price_to_text(entry)}")
            return None

        name = entry.get("name", "")
        amount = entry.get("amount", 1)
        # 普通物品：从缓存加载并设置数量
        item = self._load_item_by_name(name)
        if item is None:
            # fallback: 创建简单 Item
            item = ent.Item(name=name, item_type="misc", count=amount, weight=0.1)
        else:
            item.count = amount
            if item.weight:
                item.weight = item.weight * amount
        return item

    def _load_item_by_name(self, name: str):
        """从 data/items/ 按名称加载物品实例（委托给 _load_item_by_key）。"""
        return _load_item_by_key(name)

    def _interact_pick(self, target) -> None:
        """采摘灌木丛。"""
        tc, tr = target.pos
        # 已采摘未重生 → 空响（防御性检查，正常情况 _detect_bushes 已排除）
        regrow_at = self._state.harvested_bushes.get((tc, tr))
        if regrow_at is not None and self._state.clock.pendulum_count < regrow_at:
            self._act_log.add("灌木丛只发出了沙沙的响声")
            self._state.interact_phase = ""
            self.refresh_all()
            return
        b = random.randint(2, 5)
        berry = _load_item_by_key("浆果")
        if berry:
            berry.count = b
            _add_to_inventory(self._state.player, berry)
        self._act_log.add(f"{self._pn} 从灌木丛摘到 {b} 个浆果")
        # 记录采摘，1000 钟摆后重生
        self._state.harvested_bushes[(tc, tr)] = self._state.clock.pendulum_count + 6
        self.refresh_all()

    def _interact_rest(self, target) -> None:
        """床铺休息。"""
        self._act_log.add("不妨在床上度过舒适的一晚")
        self.refresh_all()

    def _interact_fetch_water(self, target) -> None:
        """取水：空玻璃瓶 → 一瓶水。消耗 1 钟摆。"""
        player = self._state.player
        for item in player.inventory:
            if item.name == "空玻璃瓶" and item.count > 0:
                # 移除一个空玻璃瓶
                if item.count > 1:
                    item.count -= 1
                else:
                    player.inventory.remove(item)
                # 添加一瓶水
                water = _load_item_by_key("一瓶水")
                if water:
                    water.count = 1
                    _add_to_inventory(player, water)
                self._act_log.add(f"{self._pn} 用空玻璃瓶装了满满一瓶水")
                self._state.clock.tick_action(1.0)  # 消耗 1 钟摆
                self.refresh_all()
                return
        self._act_log.add("没有空玻璃瓶可以取水")

    def _interact_door(self, target) -> None:
        """开关门。"""
        pos = target.pos
        if pos not in self._state.door_states:
            return
        is_open = self._state.door_states[pos]
        if is_open:
            self._state.door_states[pos] = False
            self._state.map[pos] = Terrain.WALL
            self._state._bump_terrain_version()
            self._act_log.add("门关上了")
        else:
            self._state.door_states[pos] = True
            self._state.map[pos] = Terrain.DOOR
            self._state._bump_terrain_version()
            self._act_log.add("门打开了")
        _update_fov(self._state)
        self.refresh_all()

    def _interact_entrance(self, target) -> None:
        """进入/离开地下城。"""
        direction = target.extra.get("direction", "enter")
        if direction == "exit":
            self._exit_dungeon()
        else:
            self._enter_dungeon()
        self.refresh_all()

    # ── 交易流程 ──

    def _interact_trade_start(self) -> None:
        """从交谈界面进入交易。"""
        target = getattr(self._state, 'interact_target', None)
        if target is None or target.creature is None:
            return
        shop_id = getattr(target.creature, 'shop_id', '') or getattr(target.creature, 'template_name', '')
        if not shop_id:
            self._act_log.add("商店数据异常")
            return
        shop = load_shop(shop_id)
        if shop is None:
            self._act_log.add(f"商店 '{shop_id}' 数据不存在")
            return
        self._state.shop_data = shop
        self._state.interact_phase = "trading"
        self._act_log.add(f"可以 :B序号 购买商品，:S序号 出售物品")
        self._wake_input()
        self.refresh_all()
        self._sync_input()

    def _handle_trade_buy(self, index: int) -> None:
        """购买商店商品。"""
        shop = self._state.shop_data
        if shop is None:
            return
        ok, msg = trade_buy(self._state.player, shop, index)
        self._act_log.add(msg)
        self.refresh_all()

    def _handle_trade_sell(self, index: int) -> None:
        """出售背包物品给商店。"""
        shop = self._state.shop_data
        if shop is None:
            return
        ok, msg = trade_sell(self._state.player, shop, index)
        self._act_log.add(msg)
        self.refresh_all()

    # ── NPC 对话 ──

    def _get_npc_dialogue(self, c: Entity) -> str:
        """基于 AI 状态生成 NPC 对话，从 dialogues.json 加载文本。"""
        enemy_count = 0
        ally_count = sum(1 for o, _ in self._state.entities
                         if o.faction == c.faction and o.hp > 0 and o is not c)
        ratio = c.hp / max(c.max_hp, 1) * (ally_count + 1)
        try:
            action, _ = _ai_engine.decide(c)
        except Exception:
            import traceback
            traceback.print_exc()
            action = "idle"

        brave = getattr(c, "bravery_tier", "medium") or "medium"

        dialogue = _load_dialogues()
        tier = brave if brave in ("low", "medium", "high") else "medium"
        action_dialogues = dialogue.get(action, dialogue.get("idle", {}))
        return f"{c.name}: {action_dialogues.get(tier, action_dialogues.get('medium', '...'))}"


    def _detect_cooking_tools(self) -> list[dict]:
        """扫描玩家 3x3 范围内厨具，徒手始终可用。"""
        pc, pr = self._state.player_pos
        tools = [{"name": "徒手", "type": "bare_hands", "pos": (pc, pr)}]
        for dc in (-1, 0, 1):
            for dr in (-1, 0, 1):
                pos = (pc + dc, pr + dr)
                if self._state.map.within_bounds(*pos) and self._state.map[pos] == Terrain.CAMPFIRE:
                    tools.append({"name": "篝火", "type": "campfire", "pos": pos})
        return tools

    def _interact_cook(self, cmd: str) -> None:
        """处理烹饪面板的 :A序号 输入。"""
        try:
            num = int(cmd[1:])
        except (ValueError, TypeError):
            self._act_log.add("用法: :A序号  如 :A1 选择第1项")
            return

        ip = self._state.interact_phase

        if ip == "cooking_tools":
            tools = getattr(self, '_cooking_tools', [])
            if num == 0:
                self._cancel_interact()
                return
            if 1 <= num <= len(tools):
                self._selected_cooking_tool = tools[num - 1]
                self._state.interact_phase = "cooking"
                self._left_panel.refresh()
            else:
                self._act_log.add("厨具序号无效")

        elif ip == "cooking":
            if num == 0:
                self._state.interact_phase = "cooking_tools"
                self._left_panel.refresh()
                return

            player = self._state.player
            cook_map = getattr(self._left_panel, '_cook_map', {})
            item = cook_map.get(num)
            if item is None:
                self._act_log.add("食材序号无效")
                return

            tool_name = getattr(self, '_selected_cooking_tool', {}).get('type', '')

            # 徒手烹饪 → 占位
            if tool_name == "bare_hands":
                self._act_log.add("[烹饪] 待定开发")
                self._state.interact_phase = ""
                self.refresh_all()
                return

            # AP/钟摆消耗
            if self._state.in_combat:
                if player.ap < 10:
                    self._act_log.add("AP 不足，无法烹饪")
                    return
                player.ap -= 10
            else:
                self._state.clock.tick_action(1.0)

            # 消耗原材料（堆叠处理）
            inv = player.inventory
            if item.count > 1:
                item.count -= 1
                unit_weight = item.weight / (item.count + 1)
                item.weight -= unit_weight
            else:
                for i, inv_item in enumerate(inv):
                    if inv_item is item:
                        inv.pop(i)
                        break

            # 查找食谱
            result_data = RECIPES.get(item.name)
            if result_data is None:
                self._act_log.add("没有匹配的食谱")
                return

            # 从 data/items/*.json 加载成品
            result_item = self._load_item_by_name(result_data["result"])
            if result_item is None:
                self._act_log.add(f"无法加载成品物品: {result_data['result']}")
                return

            _add_to_inventory(player, result_item)

            tool_name = getattr(self, '_selected_cooking_tool', {}).get('name', '?')
            if tool_name == "篝火":
                self._act_log.add(f"篝火上飘起香气，{result_data['result']}做好了")
            else:
                self._act_log.add(f"你徒手处理了{item.name}，得到了{result_data['result']}")

            self._state.interact_phase = ""
            self.refresh_all()
