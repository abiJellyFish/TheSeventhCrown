"""左侧面板 —— 探索/战斗默认面板 + 攻击流程子面板（选武器/选目标/选战技/选特殊行动）。"""

import json
import os
from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain, facing_label
from core.combat.dual_wield import dual_wield_mode, dual_wield_ap_cost
from core.actions import collect_actions, _load_special_actions

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


class LeftPanel(Static):
    state: GameState | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action_map: dict[int, tuple] = {}
        self._maneuver_map: dict[int, dict] = {}
        self._special_map: dict[int, str] = {}
        self._cook_map: dict = {}

    def render(self) -> str:
        if self.state is None:
            return ""
        # ── 交互覆盖层（优先级最高）──
        iphase = self.state.interact_phase
        if iphase == "menu":
            return self._render_interact_menu()
        if iphase == "talking":
            return self._render_talk_panel()
        if iphase == "trading":
            return self._render_trade_panel()
        if iphase == "cooking_tools":
            return self._render_cooking_tools()
        if iphase == "cooking":
            return self._render_cooking_panel()
        if iphase == "chest":
            return self._render_chest_panel()
        if iphase == "chest_take_qty":
            return self._render_chest_qty_panel("take")
        if iphase == "chest_store_qty":
            return self._render_chest_qty_panel("store")
        if iphase == "action_menu":
            return self._render_action_menu()
        if iphase == "shove_choice":
            return self._render_shove_choice()
        if iphase == "corpse":
            return self._render_corpse_panel()
        # ── 攻击流程子面板 — 探索/战斗模式共用 ──
        phase = self.state.combat_phase
        if phase == "select_spell":
            return self._render_spell_panel()
        if phase == "select_action":
            return self._render_action_panel()
        elif phase == "ranged_target":
            return self._render_aim_panel()
        elif phase == "select_maneuver":
            return self._render_maneuver_panel()
        elif phase == "select_special":
            return self._render_special_panel()
        elif phase == "adv_select":
            return self._render_adv_select_panel()
        # 探索 vs 战斗默认面板
        if self.state.in_combat:
            return self._render_combat_default()
        else:
            return self._render_explore_default()

    def _knockout_line(self) -> str:
        """击晕/杀害模式切换键文案（阶段9）：击晕模式→切换杀害，杀害模式→切换击晕。"""
        mode = getattr(self.state, 'knockout_mode', False)
        if mode:
            return "[[F]]切换杀害"
        return "[[F]]切换击晕"

    def _render_explore_default(self) -> str:
        return "\n".join([
            "[[0]]交互 [[N]]动作",
            "[[g]]慢速 [[G]]疾走  [[r]]短休 [[R]]长休  [[,]]消磨",
            "[[A]]攻击 [[S]]法术  " + self._knockout_line(),
            self._stealth_line(),
            "[[D1]]北 [[D2]]东 [[D3]]南 [[D4]]西",
        ])

    def _render_combat_default(self) -> str:
        p = self.state.player
        # 阶段7.6：AP%化（固定10格），右侧显示"剩余AP/上限"
        filled = max(0, min(10, round(p.ap / max(p.max_ap, 1) * 10)))
        lines = [
            f"AP [{'|' * filled}{'.' * (10 - filled)}] {p.ap}/{p.max_ap}",
            "S-Tab 结束战斗轮",
            "[[0]]交互 [[N]]动作",
            "[[g]]慢速 [[G]]疾走  [[r]]短休 [[R]]长休  [[,]]消磨",
            "[[A]]攻击 [[S]]法术  " + self._knockout_line(),
            self._stealth_line(),
            "[[D1]]北 [[D2]]东 [[D3]]南 [[D4]]西",
        ]
        return "\n".join(lines)

    def _stealth_line(self) -> str:
        """隐匿提示行：当前控制的实体对谁隐匿。"""
        p = self.state.player
        hidden = self.state._hidden_target_names(p)
        if hidden:
            return f"隐匿: 对{', '.join(hidden)}"
        return "隐匿: 无"

    def _render_action_menu(self) -> str:
        """动作子面板：扫描实体 actions 动态生成（D22）。"""
        actions = self.state.player.actions
        max_h = self.size.height
        lines = ["[bold]── 动作 ──[/]", ""]
        for i, a in enumerate(actions, 1):
            if len(lines) >= max_h - 1:
                lines.append(f"  ... 还有 {len(actions) - i + 1} 个动作")
                break
            name = a.get("name", a.get("key", "?"))
            cost_ap = a.get("cost_ap", 0)
            cost_p = a.get("cost_pendulum", 0)
            # 躲藏始终显示"躲藏"（起身改为独立动作 stand，阶段7.5/7.6）
            # 起身按状态动态显示费用；无倒地/躲藏状态时不显示起身
            if a.get("key") == "stand":
                prone = self.state.player.has_status("prone")
                hiding = self.state.player.has_status("hiding")
                if not prone and not hiding:
                    continue
                cost_ap = 30 if prone else 20
                cost_p = 3 if prone else 2
            lines.append(f"[[N{i}]]{name}  AP:{cost_ap} 钟摆:{cost_p}")
        lines.append("")
        lines.append("[[N0]]返回")
        return "\n".join(lines[:max_h])

    def _render_shove_choice(self) -> str:
        """推撞二选一面板（阶段6）：撞倒 / 推开。"""
        target = getattr(self.state, 'shove_target', None)
        tname = target.name if target else "目标"
        return "\n".join([
            "[bold]── 推撞 ──[/]",
            f"目标: {tname}",
            "",
            "[[S1]]撞倒  —  使目标倒地",
            "[[S2]]推开  —  将目标推离 1 格",
            "",
            "[[S0]]取消",
        ])

    def _render_corpse_panel(self) -> str:
        """尸体面板：搜刮 / 捡起。"""
        target = getattr(self.state, 'interact_target', None)
        c = target.creature if target else None
        if c is None:
            return "── 尸体 ──\n\n(目标已消失)\n\n[[0]]离开"
        looted = getattr(c, '_looted', False)
        loot_label = "搜刮(已搜刮)" if looted else "搜刮"
        lines = [
            "[bold]── 尸体 ──[/]",
            c.name,
            "",
            f"[[1]]{loot_label}",
        ]
        if getattr(c, 'corpse', None) is not None:
            lines.append("[[2]]捡起")
        lines.append("")
        lines.append("[[0]]离开")
        return "\n".join(lines[:self.size.height])


    # ── 动作收集（数据与渲染分离）──


    def _render_action_panel(self) -> str:
        actions = collect_actions(self.state)
        self._action_map = {}
        lines = ["── 选择攻击方式 ──"]
        for i, a in enumerate(actions, 1):
            self._action_map[i] = (a["mode"], a["weapon"])
            lines.append(f"[[A{i}]]{a['label']}")
        self._action_map[0] = ("cancel", None)
        lines.append("[[A0]]取消")
        return "\n".join(lines)

    def _render_spell_panel(self) -> str:
        """选择施放法术面板 —— 显示已记忆法术 + 法术位占用。"""
        from core.spell import get_memorized_spells, get_spell_slots
        p = self.state.player
        memorized = get_memorized_spells(p)
        slots = get_spell_slots(p)
        total_slots = sum(slots.values())
        used = len(memorized)
        max_h = self.size.height
        lines = ["── 选择法术 ──", f"法术位: {used}/{total_slots}", ""]
        for i, s in enumerate(memorized, 1):
            mp = s.get("mp_cost", 0)
            ap = s.get("cast_time_ap", 0)
            rng = s.get("range", 0)
            rng_str = f"射程:{rng}" if rng > 0 else "自身"
            lines.append(f"[[A{i}]]{s['name']}  MP:{mp}  AP:{ap}  {rng_str}")
        for i in range(used + 1, total_slots + 1):
            lines.append(f"[[A{i}]](空位)")
        lines.append("[[A0]]取消")
        return "\n".join(lines[:max_h])

    def _render_aim_panel(self) -> str:
        """通用瞄准面板（近战/远程/法术/投掷/点火）。只看范围，不看视野。"""
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.player_pos
        oc, oro = self.state.observe_cursor
        max_h = self.size.height

        weapon_name = weapon.name if weapon else "武器"
        # 范围：统一读 pending_attack["max_range"]，fallback 按模式推导
        if pa.get("mode") == "spell":
            spell = pa.get("spell", {})
            max_range = pa.get("max_range") or spell.get("range", 8)
            target_label = f"法术: {spell.get('name', '?')}"
        elif pa.get("mode") == "throw":
            max_range = pa.get("max_range") or pa.get("throw_max_range", pa.get("throw_range", 3))
            target_label = f"投掷: {weapon_name}"
        elif pa.get("mode") in ("torch_ignite_surface", "ignite_surface"):
            max_range = pa.get("max_range", 1)
            target_label = f"点火: {weapon_name}" if pa.get("mode") == "torch_ignite_surface" else "生火: 空玻璃瓶"
        elif pa.get("mode") == "action":
            max_range = pa.get("max_range", 1)
            target_label = f"动作: {pa.get('action_name', '动作')}"
        elif weapon and getattr(weapon, 'weapon_type', '') == "ranged":
            max_range = pa.get("max_range") or getattr(weapon, 'range_max', 1)
            target_label = f"远程: {weapon_name}"
        else:
            max_range = pa.get("max_range") or (weapon.reach if weapon and hasattr(weapon, 'reach') and weapon.reach else 1)
            target_label = f"近战: {weapon_name}"
        dist = max(abs(oc - pc), abs(oro - pr))
        in_range = dist <= max_range

        # 地表
        terrain = self.state.map[oc, oro]
        t_names = {Terrain.GRASS: "草地", Terrain.BARREN: "荒地", Terrain.PLAIN: "平原", Terrain.FLOOR: "地面", Terrain.BED: "床铺", Terrain.STAIRS_DOWN: "楼梯下", Terrain.STAIRS_UP: "楼梯上", Terrain.WATER: "水", Terrain.BUSH: "灌木丛", Terrain.STONE: "石头", Terrain.LOW_WALL: "矮墙", Terrain.TREE: "树", Terrain.CAMPFIRE: "篝火", Terrain.DOOR: "门", Terrain.WALL: "墙壁"}
        terrain_name = t_names.get(terrain, "未知")

        # 目标：范围允许即可选（含自身，不校验视野）
        ent = self.state.get_entity_at(oc, oro)
        has_valid_target = ent and not ent.is_dead

        lines = [
            "[bold]── 瞄准 ──[/]",
            f"{target_label}  范围: {max_range}",
            f"光标: ({oc}, {oro})  距离: {dist}/{max_range}"
            + (" [green]✓[/]" if in_range else " [red]超出范围[/]"),
            f"地表: {terrain_name}",
            "",
        ]

        # 多目标进度
        target_count = pa.get("target_count", 1)
        if target_count > 1:
            prog = f"目标: {min(len(pa.get('targets', [])) + 1, target_count)}/{target_count}"
            names = []
            for _, _, t in pa.get("targets", []):
                names.append(t.name if t else "空地")
            if names:
                prog += f"  已选: {', '.join(names)}"
            lines.append(prog)

        if has_valid_target:
            hp_pct = ent.hp / max(ent.max_hp, 1) * 100
            self_tag = " (你)" if ent is self.state.player else ""
            faction_tag = {"混乱": "[red]敌对[/]", "守序": "[green]友好[/]",
                           "中立": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
            lines.append(f"目标: {ent.name}{self_tag} {faction_tag}")
            lines.append(f"  朝向: {facing_label(ent.facing)}  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)  AC {ent.total_ac('chest')}")
            if ent.statuses:
                lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")
        elif terrain == Terrain.WALL:
            lines.append("目标: (墙壁)")
        else:
            lines.append("目标: (空地)")

        lines.append("")
        lines.append("[[方向键]] 移动光标  [[Enter]] 确认  [[']] 取消")
        return "\n".join(lines[:max_h])

    def _render_adv_select_panel(self) -> str:
        """优势选择面板：显示各骰面点数及序号，玩家输入序号选择。"""
        pa = self.state.pending_attack or {}
        rolls = pa.get("adv_rolls") or []
        if not rolls:
            return "── 掷骰中 ──"
        lines = ["── 优势! 选择点数 ──"]
        for i, r in enumerate(rolls, 1):
            lines.append(f"  [[{i}]] {r}")
        lines.append("")
        lines.append("输入序号选择其中一个点数")
        return "\n".join(lines)

    def _render_maneuver_panel(self) -> str:
        pa = self.state.pending_attack or {}
        target = pa.get("target")
        attack_roll = pa.get("attack_roll", 0)
        weapon = pa.get("weapon")

        target_name = target.name if target else "目标"
        target_ac = target.total_ac('chest') if target else 0

        # 从 game_state 读取战技数据
        maneuvers = getattr(self.state, 'maneuvers', [])
        self._maneuver_map = {}
        lines = ["── 命中! 选择战技 ──",
                 f"{weapon.name if weapon else '武器'}击中{target_name} (roll={attack_roll} vs AC={target_ac})"]
        for i, m in enumerate(maneuvers, 1):
            self._maneuver_map[i] = m
            desc = m.get('effect', '')
            if desc == 'damage_bonus':
                desc_text = f'伤害+{m["value"]}'
            elif desc == 'disarm':
                desc_text = '目标力量豁免失败则武器掉落'
            elif desc == 'knockdown':
                desc_text = '目标敏捷豁免失败则倒地'
            else:
                desc_text = desc
            lines.append(f"[[A{i}]]{m['name']}  AP+{m['ap_extra']}  {desc_text}")
        self._maneuver_map[0] = None
        lines.append("[[A0]]直接攻击  不消耗额外AP，正常结算伤害")
        return "\n".join(lines)

    def _render_special_panel(self) -> str:
        pa = self.state.pending_attack or {}
        target = pa.get("target")
        attack_roll = pa.get("attack_roll", 0)
        weapon = pa.get("weapon")
        p = self.state.player

        target_name = target.name if target else "目标"
        target_ac = target.total_ac('chest') if target else 0

        specials = _load_special_actions()
        self._special_map = {}
        lines = ["── 未命中 ──",
                 f"{weapon.name if weapon else '武器'}挥空{target_name} (roll={attack_roll} vs AC={target_ac})"]
        for i, s in enumerate(specials, 1):
            self._special_map[i] = s["key"]
            ap_note = " [dim]AP不足[/]" if p.ap < s["ap_cost"] else ""
            lines.append(f"[[A{i}]]{s['name']}  {s['desc']}{ap_note}")
        self._special_map[0] = "tenacity"
        lines.append("[[A0]]削韧      不消耗AP，削减目标韧性")
        return "\n".join(lines)


    # ── 交互覆盖层子面板 ──

    def _render_interact_menu(self) -> str:
        """交互目标选择菜单。"""
        targets = self.state.interact_targets
        max_h = self.size.height
        lines = ["[bold]── 交互 ──[/]", ""]
        for i, t in enumerate(targets, 1):
            if len(lines) >= max_h - 1:
                lines.append(f"  ... 还有 {len(targets) - i + 1} 个目标")
                break
            lines.append(f"[[{i}]]{t.label}")
        lines.append("")
        lines.append("[[0]]离开")
        return "\n".join(lines[:max_h])

    def _render_talk_panel(self) -> str:
        """交谈面板。"""
        target = self.state.interact_target
        max_h = self.size.height
        if target is None or target.creature is None:
            return "── 交谈 ──\n\n(无目标)\n\n[[0]]离开"
        c = target.creature
        lines = [
            f"[bold]── 与{c.name}交谈 ──[/]",
            "",
        ]
        # 显示基本状态
        hp_pct = c.hp / max(c.max_hp, 1) * 100
        faction_tag = {"混乱": "[red]敌对[/]", "守序": "[green]友好[/]",
                       "中立": "[yellow]中立[/]"}.get(c.faction, c.faction)
        lines.append(f"HP {c.hp}/{c.max_hp} ({hp_pct:.0f}%)  {faction_tag}")
        if c.statuses:
            lines.append(f"状态: {', '.join(s.name for s in c.statuses)}")
        lines.append("")
        # 交易选项
        if target.extra.get("can_trade"):
            lines.append("[[T]]交易")
        lines.append("[[0]]离开")
        return "\n".join(lines[:max_h])

    def _render_trade_panel(self) -> str:
        """交易面板：商店库存 + 玩家背包。动态反映库存变化。"""
        from core.trade import (shop_gold_text, price_to_text, copper_to_currency,
                                 player_wealth_copper, DEFAULT_STOCK_QTY)

        shop = self.state.shop_data
        p = self.state.player
        max_h = self.size.height

        if shop is None:
            return "── 交易 ──\n\n商店数据异常\n\n[[0]]离开"

        shop_name = shop.get("name", "商店")
        wealth = copper_to_currency(player_wealth_copper(p))
        lines = [
            f"[bold]── 交易 ── {shop_name}[/]  资金: {shop_gold_text(shop)}",
            f"你的金币: {price_to_text(wealth)}",
            "",
            "[bold]商店库存[/]",
        ]

        # 商店库存（含库存量，动态更新）
        stock = shop.get("_resolved_stock", [])
        for i, entry in enumerate(stock, 1):
            item = entry["item"]
            price_text = price_to_text(entry["price"])
            qty = entry.get("stock_qty", 0)
            qty_str = str(qty) if qty < DEFAULT_STOCK_QTY else "充足"
            lines.append(f"[[B{i}]]{item.name}  {price_text}  库存:{qty_str}")
        if not stock:
            lines.append("  (已售罄)")

        lines.append("")
        lines.append("[bold]你的背包[/]")

        # 玩家背包
        shown = 0
        for item in p.inventory:
            sell_p = sell_price_local(item.price)
            count_str = f" x{item.count}" if item.count > 1 else ""
            lines.append(f"[[S{shown + 1}]]{item.name}{count_str}  售价:{price_to_text(sell_p)}")
            shown += 1
        if shown == 0:
            lines.append("  (无可出售物品)")

        lines.append("")
        lines.append(":B序号 购买  :S序号 出售  [[0]]离开")
        return "\n".join(lines[:max_h])


    # ── 烹饪面板 ──

    def _render_cooking_tools(self) -> str:
        """厨具选择面板。"""
        tools = getattr(self.app, '_cooking_tools', [])
        lines = ["[bold]── 选择厨具 ──[/]", ""]
        if not tools:
            lines.append("附近没有可用的厨具")
        else:
            for i, tool in enumerate(tools):
                lines.append(f"[[A{i+1}]]{tool['name']}")
        lines.append("")
        lines.append("[[A0]]返回")
        return "\n".join(lines)

    def _render_cooking_panel(self) -> str:
        """烹饪原材料选择面板。"""
        from render.textual.controllers.interact import RECIPES
        player = self.state.player
        tool_name = getattr(self.app, '_selected_cooking_tool', {}).get('name', '?')
        lines = [f"[bold]── 烹饪（{tool_name}）──[/]", ""]
        idx = 1
        self._cook_map = {}
        for item in player.inventory:
            if item.name in RECIPES:
                self._cook_map[idx] = item
                lines.append(f"[[A{idx}]]{item.name} x{item.count}")
                idx += 1
        if idx == 1:
            lines.append("没有可烹饪的食材")
        lines.append("")
        lines.append("[[A0]]返回")
        return "\n".join(lines)


    def _render_chest_panel(self) -> str:
        """箱子交互面板：拿取区 + 存放区。"""
        target = getattr(self.state, 'interact_target', None)
        if target is None:
            return "── 箱子 ──\n\n(数据异常)\n\n[0] 离开"

        chest_data = target.extra.get("chest_data", {})
        label = chest_data.get("label", "箱子")
        gp = chest_data.get("gp", 0)
        chest_inv = chest_data.get("inventory", [])
        max_h = self.size.height

        lines = [f"[bold]── {label} ──[/]", ""]
        if gp > 0:
            lines.append(f"金币: {gp} GP")
        lines.append("")

        # 拿取区
        lines.append("[bold][拿取][/]")
        if chest_inv:
            for i, item in enumerate(chest_inv, 1):
                name = item.name
                count = getattr(item, 'count', 1)
                count_str = f" x{count}" if count > 1 else ""
                lines.append(f"  [[C{i}]]{name}{count_str}")
        else:
            lines.append("  (箱子为空)")
        lines.append("")

        # 存放区
        lines.append("[bold][存放]（你的物品栏）[/]")
        player_inv = self.state.player.inventory
        if player_inv:
            for i, item in enumerate(player_inv, 1):
                count_str = f" x{item.count}" if item.count > 1 else ""
                lines.append(f"  [[S{i}]]{item.name}{count_str}")
        else:
            lines.append("  (背包为空)")
        lines.append("")

        lines.append(":C序号 拿取  :S序号 存放  [0] 离开")
        return "\n".join(lines[:max_h])

    def _render_chest_qty_panel(self, mode: str) -> str:
        """箱子数量选择面板。mode: "take" | "store" """
        target = getattr(self.state, 'interact_target', None)
        if target is None:
            return "── 箱子 ──\n\n(数据异常)\n\n[0] 返回"
        extra = target.extra
        item = extra.get("_qty_item")
        max_qty = extra.get("_qty_max", 1)
        if item is None:
            return "── 箱子 ──\n\n(数据异常)\n\n[0] 返回"
        action = "拿取" if mode == "take" else "存放"
        prefix = "C" if mode == "take" else "S"
        return "\n".join([
            f"[bold]── {action} {item.name} ──[/]",
            f"可选: 1 - {max_qty}",
            "",
            f"输入 :{prefix}数量 确认  [0] 返回",
        ])


def sell_price_local(price: dict) -> dict:
    """半价收购价（避免循环导入）。"""
    from core.trade import sell_price
    return sell_price(price)


