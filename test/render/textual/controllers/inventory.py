"""物品/装备控制器 —— 使用、装备/卸除、交换、拾取/丢弃、物品菜单。"""
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
from core.loot import _add_to_inventory
from render.textual.fov import _update_fov



class InventoryMixin:

    def _use_item(self, cmd: str) -> None:
        """选择背包物品：I + 序号，推入物品交互菜单栈。"""
        try:
            idx = int(cmd[1:]) - 1
            inv = self._state.player.inventory
            if 0 <= idx < len(inv):
                item = inv[idx]
                stack = self._state.item_menu_stack
                # 保存物品在背包中的索引，供后续操作使用
                stack.append({
                    "type": "item_actions",
                    "item": item,
                    "inv_index": idx,
                    "options": [{"label": label, "action": label} for label in get_item_actions(item)],
                })
            else:
                self._act_log.add("物品序号无效")
        except (ValueError, IndexError):
            self._act_log.add("用法: :I序号  如 :I1 选择第1个物品")
        self._right_panel.refresh()
        self._wake_input()

    def _take_one_from_stack(self, item, inv, idx):
        """从堆叠物品中取出一件。count>1 则减 count 退回单件；count==1 则 pop。
        返回单件物品，失败返回 None。"""
        if item.count > 1:
            unit_weight = item.weight / item.count
            item.count -= 1
            item.weight -= unit_weight
            return copy_item_with_count(item, 1, unit_weight)
        else:
            return inv.pop(idx)

    # ── 装备/卸除/互换 ──

    def _equip_to_hand(self, item) -> None:
        """装备单手武器/盾牌到手部。先试左手，被占试右手，都被占则与左手互换。"""
        equip = self._state.player.equipment

        # 双手武器：先装到空闲手，另一手自动卸除
        props = getattr(item, 'properties', []) or []
        is_two_handed = 'two_handed' in props

        if is_two_handed:
            # 两手全部卸除，武器放到右手；逐手日志
            for hand in ("left_hand", "right_hand"):
                old = equip.get(hand)
                if old is not None:
                    self._extinguish_torch_if_lit(old)
                    equip[hand] = None
                    _add_to_inventory(self._state.player, old)
                    hand_name = "左手" if hand == "left_hand" else "右手"
                    self._act_log.add(f"{self._pn} 卸下了{hand_name}的{old.name}")
            equip["right_hand"] = item
            self._act_log.add(f"{self._pn} 双手握持了 {item.name}")
            return

        # 单手：左 → 右 顺序。先检查另一只手是否有双手武器
        for hand in ("left_hand", "right_hand"):
            if equip.get(hand) is None:
                other_hand = "right_hand" if hand == "left_hand" else "left_hand"
                other = equip.get(other_hand)
                if other is not None:
                    other_props = getattr(other, 'properties', []) or []
                    if 'two_handed' in other_props:
                        # 另一只手是双手武器 → 卸除它
                        self._extinguish_torch_if_lit(other)
                        equip[other_hand] = None
                        _add_to_inventory(self._state.player, other)
                        self._act_log.add(f"{self._pn} 收起了{other.name}（双手），装备了 {item.name}")
                        equip[hand] = item
                        return
                equip[hand] = item
                hand_name = "左手" if hand == "left_hand" else "右手"
                self._act_log.add(f"{self._pn} 装备了 {item.name}（{hand_name}）")
                return

        # 都占，与左手互换
        old = equip["left_hand"]
        self._extinguish_torch_if_lit(old)
        equip["left_hand"] = item
        _add_to_inventory(self._state.player, old)
        self._act_log.add(f"{self._pn} 收起了{old.name}，装备了{item.name}（左手）")

    def _equip_armor_from_inventory(self, armor: "ent.Armor") -> None:
        """从物品栏装备护甲到对应部位。"""
        equip = self._state.player.equipment
        p = self._state.player

        slot = armor.slot
        # 盾牌视作单手装备
        if armor.armor_type == "shield":
            self._equip_shield(armor)
            return
        # 全身服饰 → 胸甲位
        if slot == "full_body":
            slot = "chest"
        old = equip.get(slot)
        if old is not None:
            _add_to_inventory(self._state.player, old)

        equip[slot] = armor
        # 更新 AC
        ac_field = {"head": "ac_head", "chest": "ac_chest", "arms": "ac_arms", "legs": "ac_legs"}.get(slot)
        if ac_field:
            setattr(p, ac_field, getattr(p, ac_field) + armor.ac_bonus)
        self._act_log.add(f"{self._pn} 装备了 {armor.name}")

    def _equip_shield(self, shield) -> None:
        """装备盾牌：先试左手，被占试右手，都被占则与左手互换（与单手武器规则一致）。"""
        equip = self._state.player.equipment
        p = self._state.player

        for hand in ("left_hand", "right_hand"):
            if equip.get(hand) is None:
                equip[hand] = shield
                p.ac_shield += shield.ac_bonus
                hand_name = "左手" if hand == "left_hand" else "右手"
                self._act_log.add(f"{self._pn} 装备了 {shield.name}（{hand_name}）")
                return

        # 都占，与左手互换
        old = equip["left_hand"]
        equip["left_hand"] = shield
        _add_to_inventory(self._state.player, old)
        # AC：去除旧物品的 shield AC（如果是盾牌），添加新盾牌 AC
        if old.armor is not None and old.armor_type == "shield":
            p.ac_shield = max(0, p.ac_shield - old.ac_bonus)
        p.ac_shield += shield.ac_bonus
        self._act_log.add(f"{self._pn} 收起了{old.name}，装备了 {shield.name}（左手）")

    def _extinguish_torch_if_lit(self, item) -> None:
        """如果物品是已点燃的火把/光源，则熄灭并注销光源。"""
        ls = item.light
        if not ls:
            return
        if ls.condition == "lit":
            ls.condition = "unlit"
            self._state.unregister_light(self._state.player_pos)
            self._act_log.add(f"{item.name} 被收起，火光熄灭了")
            _update_fov(self._state)

    def _unequip_slot(self, slot: str) -> None:
        """卸除指定部位的装备，放入背包。双手武器从任一手卸除均可。"""
        p = self._state.player
        equip = p.equipment
        item = equip.get(slot)
        if item is None and slot in ("left_hand", "right_hand"):
            # 空手但另一只手有双手武器 → 卸除双手武器
            other_slot = "right_hand" if slot == "left_hand" else "left_hand"
            other = equip.get(other_slot)
            if other is not None:
                other_props = getattr(other, 'properties', []) or []
                if 'two_handed' in other_props:
                    item = other
                    slot = other_slot
        if item is None:
            self._act_log.add(f"该部位没有装备")
            return

        # 卸除前：若火把已点燃则自动熄灭
        self._extinguish_torch_if_lit(item)

        equip[slot] = None
        _add_to_inventory(self._state.player, item)

        # 重算对应 AC
        if slot in ("left_hand", "right_hand"):
            if item.armor is not None and item.armor_type == "shield":
                p.ac_shield = max(0, p.ac_shield - item.ac_bonus)
        else:
            ac_field = {"head": "ac_head", "chest": "ac_chest", "arms": "ac_arms", "legs": "ac_legs"}.get(slot)
            if ac_field and item.armor is not None:
                setattr(p, ac_field, max(0, getattr(p, ac_field) - item.ac_bonus))

        slot_names = {"left_hand": "左手", "right_hand": "右手", "head": "头部",
                      "chest": "躯干", "arms": "双臂", "legs": "双腿"}
        slot_name = slot_names.get(slot, slot)
        self._act_log.add(f"{self._pn} 卸下了 {item.name}（{slot_name}）")
        self._right_panel.refresh()

    UNEQUIP_SLOTS = {
        1: "left_hand", 2: "right_hand",
        3: "head", 4: "chest", 5: "arms", 6: "legs",
    }

    def _handle_unequip(self, cmd: str) -> None:
        """处理卸除命令：:U1~:U6。"""
        try:
            idx = int(cmd[1:])
            slot = self.UNEQUIP_SLOTS.get(idx)
            if slot is None:
                self._act_log.add("用法: :U1 左手 :U2 右手 :U3 头部 :U4 躯干 :U5 双臂 :U6 双腿")
                return
            self._unequip_slot(slot)
        except (ValueError, IndexError):
            self._act_log.add("用法: :U1 左手 :U2 右手 :U3 头部 :U4 躯干 :U5 双臂 :U6 双腿")
        self._right_panel.refresh()

    def _swap_hands(self, cmd: str = "") -> None:
        """交换左右手装备。"""
        equip = self._state.player.equipment
        left = equip.get("left_hand")
        right = equip.get("right_hand")

        # 检查双手武器
        for item in (left, right):
            if item is not None and hasattr(item, 'properties') and item.properties:
                if 'two_handed' in item.properties:
                    self._act_log.add("双手武器不能交换")
                    return

        equip["left_hand"], equip["right_hand"] = right, left
        self._act_log.add(f"{self._pn} 交换了左右手装备")
        self._right_panel.refresh()

    def _on_two_hand_equip(self, weapon, hand: str = "right") -> None:
        """双手并用时卸除另一只手的武器。hand 为武器所在手。"""
        equip = self._state.player.equipment
        other_hand = "right_hand" if hand == "left" else "left_hand"
        other = equip.get(other_hand)
        if other is not None:
            equip[other_hand] = None
            _add_to_inventory(self._state.player, other)
        self._act_log.add(f"{self._pn} 双手握持了 {weapon.name}")
        self._sync_carry_status()

    def _sync_carry_status(self) -> None:
        """同步负重状态到 creature.statuses。"""
        p = self._state.player
        status = p.carry_status()
        # 移除旧负重状态
        for old in ("轻便", "负重", "超重"):
            p.remove_status(old)
        # 始终显示负重状态
        p.add_status(status["label"])

    def _apply_item_effect(self, item) -> None:
        """根据物品 effect 字段应用效果，支持数值和骰子字符串。"""
        eff = item.effect
        amt = item.amount
        p = self._state.player

        # 解析数值或骰子字符串
        try:
            val = int(amt)
        except (ValueError, TypeError):
            if isinstance(amt, str) and "d" in amt:
                count, sides = parse_dice(amt)
                val = roll_dice(count, sides)
            else:
                val = 0

        if eff == "heal" and val > 0:
            p.hp = min(p.max_hp, p.hp + val)
            self._act_log.add(f"  恢复了 {val} 点生命")
        elif eff == "restore_mp" and val > 0:
            p.mp = min(p.max_mp, p.mp + val)
            self._act_log.add(f"  恢复了 {val} 点精神")
        elif eff == "restore_food":
            if val > 0:
                p.food_value = min(15000, p.food_value + val)
            self._act_log.add(f"  恢复了 {val or '一定'} 饮食值")

    # ── 物品交互菜单 ──

    def _cmd_item_action(self, cmd: str) -> None:
        """处理物品交互菜单的 U 命令。"""
        stack = self._state.item_menu_stack
        if not stack:
            return
        top = stack[-1]
        menu_type = top.get("type", "")

        try:
            num = int(cmd[1:])
        except (ValueError, TypeError):
            self._act_log.add("用法: :U序号  如 :U1 选择第1项")
            return

        if menu_type == "item_actions":
            self._handle_item_menu_select(num, top)
        elif menu_type == "quantity_select":
            self._handle_quantity_select(num, top)
        elif menu_type == "pickup_quantity":
            self._handle_pickup_quantity(num, top)
        else:
            self._act_log.add(f"未知菜单类型: {menu_type}")

        self.refresh_all()
        self._right_panel.refresh()
        self._map_view.refresh()

    def _handle_item_menu_select(self, num: int, top: dict) -> None:
        """处理一级菜单（物品操作选项）选择。"""
        stack = self._state.item_menu_stack
        options = top.get("options", [])
        item = top.get("item")
        inv_index = top.get("inv_index", -1)

        if num == 0:
            stack.pop()
            return

        if num < 1 or num > len(options):
            self._act_log.add("选项无效")
            return

        action_label = options[num - 1]["label"]

        if action_label == "丢弃":
            if item.count > 1:
                stack.append({
                    "type": "quantity_select",
                    "item": item,
                    "inv_index": inv_index,
                })
            else:
                self._exec_drop(item, inv_index, 1)
                stack.pop()
            return

        if action_label == "食用":
            if item.count > 1:
                stack.append({
                    "type": "quantity_select",
                    "mode": "eat",
                    "item": item,
                    "inv_index": inv_index,
                })
            else:
                self._action_use_consumable(item, inv_index)
                stack.pop()
            return

        if action_label == "投掷":
            # 检查力量要求
            throw_str_req = getattr(item, 'throw_str_req', 0)
            if throw_str_req > 0 and self._state.player.stat("str") < throw_str_req:
                self._act_log.add("力量不足，无法投掷此物品")
                return
            # 进入投掷瞄准模式
            throw_range = get_throw_range(item, self._state.player.vision_range)
            throw_max = get_throw_max_range(item, throw_range)
            self._state.pending_attack = {
                "mode": "throw",
                "weapon": item,
                "throw_item": item,
                "throw_inv_index": inv_index,
                "throw_range": throw_range,
                "throw_max_range": throw_max,
                "max_range": throw_max,
            }
            self._state.combat_phase = "ranged_target"
            self._state.observe_mode = False
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add(f"选择投掷目标 — 射程:{throw_range} [方向键]移动 [Enter]确认 [']取消")
            stack.clear()  # 退出物品菜单，进入瞄准
            self._close_input()
            self.refresh_all()
            return

        # ---- 哈希表分发 ----
        handler = self._ITEM_ACTION_HANDLERS.get(action_label)
        if handler:
            handler(self, item, inv_index)
            # 物品使用/装备 → 破坏隐匿
            self._state._break_stealth_in_view(self._state.player)
            # 执行成功后返回物品栏
            stack.pop()
            return

        self._act_log.add(f"未知操作: {action_label}")

    def _handle_quantity_select(self, num: int, top: dict) -> None:
        """处理数量选择菜单。"""
        stack = self._state.item_menu_stack
        item = top.get("item")
        inv_index = top.get("inv_index", -1)
        mode = top.get("mode", "")

        if num == 0:
            stack.pop()
            return

        # 食用模式
        if mode == "eat":
            player = self._state.player
            max_qty = item.count if item else 0
            if self._state.in_combat:
                # 每份 1AP，AP 不足时限制可选数量
                max_qty = min(max_qty, player.ap)
            if num > max_qty:
                self._act_log.add(f"数量无效，最多可选 {max_qty} 份")
                return
            for _ in range(num):
                if item.count <= 0:
                    break
                self._action_use_consumable(item, inv_index)
                if not self._state.in_combat:
                    self._state.clock.tick_action(1.0)
            # 回退到物品栏
            stack.pop()
            if stack:
                stack.pop()
            return

        # 原有丢弃逻辑
        max_qty = item.count if item else 0
        if 1 <= num <= max_qty:
            self._exec_drop(item, inv_index, num)
            # 丢弃后回退两层（数量选择 + 物品操作菜单）
            stack.pop()
            if stack:
                stack.pop()
        else:
            self._act_log.add(f"数量无效 (1-{max_qty})")

    def _handle_pickup_quantity(self, num: int, top: dict) -> None:
        """处理捡起数量选择菜单。"""
        stack = self._state.item_menu_stack
        item = top.get("item")
        pos = top.get("pos", (0, 0))

        if num == 0:
            stack.clear()
            self._cancel_interact()
            return

        max_qty = item.count if item else 0
        if 1 <= num <= max_qty:
            self._exec_pickup(item, pos, num)
            stack.clear()
            self._cancel_interact()
        else:
            self._act_log.add(f"数量无效 (1-{max_qty})")

    def _exec_drop(self, item, inv_index: int, quantity: int) -> None:
        """执行丢弃：从背包扣除 → BFS 找放置格 → 放到地上。"""
        player = self._state.player
        pc, pr = self._state.player_pos

        dropped = item_remove_from_inventory(player, inv_index, quantity)
        if dropped is None:
            self._act_log.add("丢弃失败：物品数量不足")
            return

        # BFS 查找放置格
        target_pos = find_placeable_tile(
            self._state.ground_items, pc, pr, dropped,
            self._state.map.width, self._state.map.height,
            map=self._state.map, entities=self._state.entities,
        )
        if target_pos is None:
            # 找不到空位，退回物品
            _add_to_inventory(player, dropped)
            self._act_log.add("周围没有空间丢弃物品")
            return

        place_on_ground(self._state.ground_items, dropped, target_pos[0], target_pos[1])
        self._act_log.add(f"{self._pn} 丢弃了 {dropped.name}" + (f" x{quantity}" if quantity > 1 else ""))
        self._map_view.refresh()
        self._right_panel.refresh()

    def _exec_pickup(self, item, pos: tuple[int, int], quantity: int) -> None:
        """执行捡起：从地上移除 → 加入玩家背包。"""
        player = self._state.player
        ground = self._state.ground_items

        # 查找地上物品索引
        gidx = None
        for i, (it, (ic, ir)) in enumerate(ground):
            if it is item and (ic, ir) == pos:
                gidx = i
                break

        if gidx is None:
            self._act_log.add("物品已不在原地")
            return

        if quantity >= item.count:
            # 全部捡起
            ground.pop(gidx)
            picked = item
        else:
            # 部分捡起
            unit_weight = item.weight / item.count if item.count > 0 else 0
            item.count -= quantity
            item.weight -= unit_weight * quantity
            picked = copy_item_with_count(item, quantity, unit_weight * quantity)

        _add_to_inventory(player, picked)
        self._act_log.add(f"{self._pn} 捡起了 {picked.name}" + (f" x{quantity}" if quantity > 1 else ""))
        self._map_view.refresh()
        self._right_panel.refresh()

    def _equip_to_specific_hand(self, item, hand: str) -> None:
        """装备物品到指定手部槽位（left_hand / right_hand）。"""
        equip = self._state.player.equipment
        props = getattr(item, 'properties', []) or []
        is_two_handed = 'two_handed' in props

        if is_two_handed:
            # 双手武器：两手持握
            for h in ("left_hand", "right_hand"):
                old = equip.get(h)
                if old is not None:
                    equip[h] = None
                    _add_to_inventory(self._state.player, old)
                    hand_name = "左手" if h == "left_hand" else "右手"
                    self._act_log.add(f"{self._pn} 卸下了{hand_name}的{old.name}")
            equip["right_hand"] = item
            self._act_log.add(f"{self._pn} 双手握持了 {item.name}")
            return

        # 单手武器：先检查另一只手是否有双手武器
        other_hand = "right_hand" if hand == "left_hand" else "left_hand"
        other = equip.get(other_hand)
        if other is not None:
            other_props = getattr(other, 'properties', []) or []
            if 'two_handed' in other_props:
                equip[other_hand] = None
                _add_to_inventory(self._state.player, other)
                self._act_log.add(f"{self._pn} 收起了{other.name}（双手），准备装备 {item.name}")

        # 单手武器：目标手被占则互换
        old = equip.get(hand)
        equip[hand] = item
        if old is not None:
            _add_to_inventory(self._state.player, old)
            hand_name = "左手" if hand == "left_hand" else "右手"
            self._act_log.add(f"{self._pn} 收起了{old.name}，装备了{item.name}（{hand_name}）")
        else:
            hand_name = "左手" if hand == "left_hand" else "右手"
            self._act_log.add(f"{self._pn} 装备了 {item.name}（{hand_name}）")

    # ── 物品操作哈希表分发 ──

    def _action_equip_left(self, item, inv_index: int) -> None:
        single = self._take_one_from_stack(item, self._state.player.inventory, inv_index)
        if single:
            self._equip_to_specific_hand(single, "left_hand")

    def _action_equip_right(self, item, inv_index: int) -> None:
        single = self._take_one_from_stack(item, self._state.player.inventory, inv_index)
        if single:
            self._equip_to_specific_hand(single, "right_hand")

    def _action_equip_armor(self, item, inv_index: int) -> None:
        single = self._take_one_from_stack(item, self._state.player.inventory, inv_index)
        if single:
            self._equip_armor_from_inventory(single)

    def _action_use_consumable(self, item, inv_index: int) -> None:
        """使用消耗品（饮用/食用）。"""
        player = self._state.player
        inv = player.inventory

        cost = item.ap_cost
        if self._state.in_combat and player.ap < cost:
            self._act_log.add("AP 不足，无法使用物品")
            return

        # 空玻璃瓶生火 — 需要选择相邻格点火
        if item.effect == "start_fire":
            if not self._is_bright_or_near_light():
                self._act_log.add("光线不足，无法聚焦阳光生火")
                return
            self._state.combat_phase = "ranged_target"
            self._state.observe_mode = False
            self._state.pending_attack = {
                "mode": "ignite_surface",
                "item": item,
                "inv_index": inv_index,
                "max_range": 1,
            }
            self._state.observe_cursor = self._state.player_pos
            self._act_log.add("选择相邻一格生火 (方向键移动, Enter确认, '取消)")
            self.refresh_all()
            return

        if item.count > 1:
            item.count -= 1
            unit_weight = item.weight / (item.count + 1) if item.count > 0 else 0
            item.weight -= unit_weight
        else:
            inv.pop(inv_index)

        if self._state.in_combat:
            player.ap -= cost
        self._act_log.add(f"{self._pn} 使用了 {item.name}")

        # dc_check 检定：直接食用带毒物品需过体质检定
        raw_data = _build_item_cache().get(item.name, {})
        dc_check = raw_data.get("dc_check")
        if dc_check:
            stat = dc_check.get("stat", "con")
            dc_val = dc_check.get("dc", 15)
            on_fail = dc_check.get("on_fail", "")
            adjust = player.stat_adjust(stat)
            success, roll = check_dc(adjust, dc_val)
            if not success:
                self._act_log.add(f"体质检定失败 (d20+{adjust}={roll+adjust} vs DC{dc_val})")
                if on_fail:
                    match = re.match(r"(.+)\((\d+)钟摆\)", on_fail)
                    if match:
                        status_name = match.group(1)
                        duration = int(match.group(2))
                        player.add_status(status_name, duration)
                        self._act_log.add(f"{player.name} {status_name}了！")
                return  # 检定失败，不恢复饮食值
            else:
                self._act_log.add(f"体质检定成功 (d20+{adjust}={roll+adjust} vs DC{dc_val})")

        self._apply_item_effect(item)

        # 使用后变成新物品（如空玻璃瓶）
        becomes = _build_item_cache().get(item.name, {}).get("becomes")
        if becomes:
            result_item = self._load_item_by_name(becomes)
            if result_item is not None:
                _add_to_inventory(player, result_item)
                self._act_log.add(f"  获得了 {becomes}")

    def _on_torch_action(self, item, mode: str) -> None:
        """火把点燃/熄灭回调（由 CombatFlow 的动作处理触发）。"""
        ls = item.light
        if ls is None:
            return
        radius = ls.radius
        level = LightLevel.BRIGHT if ls.level == "bright" else LightLevel.DIM

        if mode == "torch_ignite":
            self._state.register_light(self._state.player_pos, radius, level)
            ls.condition = "lit"
            self._act_log.add(f"{self._pn} 点燃了 {item.name}")
        else:
            self._state.unregister_light(self._state.player_pos)
            ls.condition = "unlit"
            self._act_log.add(f"{self._pn} 熄灭了 {item.name}")

        _update_fov(self._state)
        self.refresh_all()

    # 物品操作 → 方法映射表
    _ITEM_ACTION_HANDLERS = {
        "装备(左手)": _action_equip_left,
        "装备(右手)": _action_equip_right,
        "装备": _action_equip_armor,
        "饮用(治疗)": _action_use_consumable,
        "饮用(回蓝)": _action_use_consumable,
        "食用": _action_use_consumable,
        "使用": _action_use_consumable,
        "点燃": _action_use_consumable,
    }

    # ── 捡起交互 ──

