"""左侧面板 —— 探索/战斗默认面板 + 攻击流程子面板（选武器/选目标/选战技/选特殊行动）。"""

import json
import os
from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain
from core.combat.dual_wield import dual_wield_mode, dual_wield_ap_cost

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


class LeftPanel(Static):
    state: GameState | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action_map: dict[int, tuple] = {}
        self._maneuver_map: dict[int, dict] = {}
        self._special_map: dict[int, str] = {}

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
        # ── 攻击流程子面板 — 探索/战斗模式共用 ──
        phase = self.state.combat_phase
        if phase == "select_action":
            return self._render_action_panel()
        elif phase == "ranged_target":
            return self._render_ranged_target_panel()
        elif phase == "select_target":
            return self._render_target_panel()
        elif phase == "select_maneuver":
            return self._render_maneuver_panel()
        elif phase == "select_special":
            return self._render_special_panel()
        # 探索 vs 战斗默认面板
        if self.state.in_combat:
            return self._render_combat_default()
        else:
            return self._render_explore_default()

    def _render_explore_default(self) -> str:
        return "\n".join([
            "[[0]]交互 [[1]]探查  [[2]]躲藏 [[3]]协助",
            "[[4]]跳跃 [[5]]撤离  [[6]]回避 [[7]]推撞",
            "[[8]]擒抱 [[ / ]]击晕  [[g]]慢速 [[G]]疾走",
            "[[r]]短休 [[R]]长休  [[,]]消磨 [[A]]攻击",
            "[[S]]法术",
        ])

    def _render_combat_default(self) -> str:
        p = self.state.player
        filled = int(p.ap / max(p.max_ap, 1) * 10)
        lines = [
            f"AP [{'|' * filled}{'.' * (10 - filled)}]",
            "S-Tab 结束战斗轮",
            "[[0]]交互 [[1]]探查  [[2]]躲藏 [[3]]协助",
            "[[4]]跳跃 [[5]]撤离  [[6]]回避 [[7]]推撞",
            "[[8]]擒抱 [[ / ]]击晕  [[g]]慢速 [[G]]疾走",
            "[[r]]短休 [[R]]长休  [[,]]消磨 [[A]]攻击",
            "[[S]]法术",
        ]
        return "\n".join(lines)

    def _is_two_handed(self, item) -> bool:
        props = getattr(item, 'properties', []) or []
        return 'two_handed' in props

    def _weapon_ap_display(self, weapon) -> str:
        """返回武器的 AP 消耗显示字符串，含弹药装填信息。"""
        props = getattr(weapon, 'properties', []) or []
        if "ammo" in props and not getattr(weapon, 'loaded', True):
            return f"装填1+攻击{weapon.ap_cost}AP (未装填)"
        return f"AP:{weapon.ap_cost}"

    # ── 动作收集（数据与渲染分离）──

    def _collect_actions(self) -> list[dict]:
        """收集当前装备状态下的所有可用攻击动作。返回动作列表，每项: {mode, weapon, label}。"""
        p = self.state.player
        left = p.equipment.get("left_hand")
        right = p.equipment.get("right_hand")
        actions = []

        # 分析手部状态
        def hand(weapon, other_weapon):
            """返回手部信息: kind, weapon, can_attack, is_light, ap"""
            if weapon is None:
                if other_weapon and self._is_two_handed(other_weapon):
                    return {"kind": "blocked", "weapon": None, "can_attack": False}
                return {"kind": "unarmed", "weapon": None, "can_attack": True,
                        "is_light": True, "ap": 1, "name": "徒手"}
            if not hasattr(weapon, 'weapon_type'):
                return {"kind": "shield", "weapon": weapon, "can_attack": False}
            if self._is_two_handed(weapon):
                return {"kind": "two_handed", "weapon": weapon, "can_attack": False}
            props = getattr(weapon, 'properties', []) or []
            return {"kind": "weapon", "weapon": weapon, "can_attack": True,
                    "is_light": 'light' in props,
                    "ap": weapon.ap_cost, "name": weapon.name,
                    "damage": weapon.damage, "damage_type": weapon.damage_type}

        L = hand(left, right)
        R = hand(right, left)

        # 1) 单手武器
        for side, h in [("left", L), ("right", R)]:
            hand_label = "左手" if side == "left" else "右手"
            if h["kind"] == "weapon":
                w = h["weapon"]
                actions.append({"mode": f"{side}_hand", "weapon": w,
                    "label": f"{hand_label}武器  {w.name} {w.damage} {w.damage_type} {self._weapon_ap_display(w)}"})
            elif h["kind"] == "shield":
                actions.append({"mode": f"{side}_hand_blocked", "weapon": h["weapon"],
                    "label": f"{hand_label}武器  {h['weapon'].name} (不能攻击)"})

        # 2) 徒手
        for side, h in [("left", L), ("right", R)]:
            hand_label = "左手" if side == "left" else "右手"
            if h["kind"] == "unarmed":
                actions.append({"mode": f"unarmed_{side}", "weapon": None,
                    "label": f"徒手打击({hand_label})  1+力量 钝击 AP:1"})

        # 3) 双持 — 两手都能攻击且都不是双手武器
        if L["can_attack"] and R["can_attack"]:
            l_light = L["is_light"]
            r_light = R["is_light"]
            l_ap = L["ap"]; r_ap = R["ap"]
            l_name = L["name"]; r_name = R["name"]
            if l_light and r_light:
                ap = max(l_ap, r_ap)
                actions.append({"mode": "dual_wield", "weapon": R.get("weapon") or "unarmed",
                    "label": f"双持武器  {l_name}+{r_name} AP:{ap}"})
            else:
                actions.append({"mode": "dual_attack", "weapon": R.get("weapon") or "unarmed",
                    "label": f"双持攻击  {l_name}({l_ap}AP)+{r_name}({r_ap}AP)"})

        # 4) 双手武器 — 单条
        for h in [L, R]:
            if h["kind"] == "two_handed":
                w = h["weapon"]
                actions.append({"mode": "two_hand", "weapon": w,
                    "label": f"双手并用  {w.name} {self._weapon_ap_display(w)}"})
                break

        # 5) 双手并用（两用武器）— 一手武器近战 + 另一手空
        for side, h, other in [("left", L, R), ("right", R, L)]:
            hand_label = "左手" if side == "left" else "右手"
            if h["kind"] == "weapon" and h["weapon"].weapon_type == "melee" \
               and other["kind"] == "unarmed":
                w = h["weapon"]
                actions.append({"mode": f"two_hand_{side}", "weapon": w,
                    "label": f"双手并用({hand_label})  {w.name} 命中+1 伤害+2 AP:{w.ap_cost}"})

        # 6) 远程武器近战
        for h in [L, R]:
            if h["kind"] == "two_handed" and h["weapon"].weapon_type == "ranged" \
               and getattr(h["weapon"], 'melee', None):
                w = h["weapon"]; m = w.melee
                actions.append({"mode": "ranged_melee", "weapon": w,
                    "label": f"双手攻击(近战)  {w.name} {m['damage']}+力量 {m['damage_type']} AP:{m['ap_cost']}"})
                break

        return actions

    def _render_action_panel(self) -> str:
        actions = self._collect_actions()
        self._action_map = {}
        lines = ["── 选择攻击方式 ──"]
        for i, a in enumerate(actions, 1):
            self._action_map[i] = (a["mode"], a["weapon"])
            lines.append(f"[[A{i}]]{a['label']}")
        self._action_map[0] = ("cancel", None)
        lines.append("[[A0]]取消")
        return "\n".join(lines)

    def _render_ranged_target_panel(self) -> str:
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.player_pos
        oc, oro = self.state.observe_cursor
        max_h = self.size.height

        weapon_name = weapon.name if weapon else "武器"
        max_range = weapon.range_max if weapon and hasattr(weapon, 'range_max') else 1
        dist = max(abs(oc - pc), abs(oro - pr))
        in_range = dist <= max_range

        # 地表
        terrain = self.state.map[oc, oro]
        t_names = {Terrain.WALL: "墙壁", Terrain.DIFFICULT: "灌木", Terrain.PASSABLE: "草地"}
        terrain_name = t_names.get(terrain, "未知")

        # 目标
        ent = self.state.get_entity_at(oc, oro)
        has_valid_target = ent and ent.hp > 0 and ent is not self.state.player

        lines = [
            "[bold]── 远程瞄准 ──[/]",
            f"武器: {weapon_name}  射程: {max_range}",
            f"光标: ({oc}, {oro})  距离: {dist}/{max_range}"
            + (" [green]✓[/]" if in_range else " [red]超出射程[/]"),
            f"地表: {terrain_name}",
            "",
        ]

        if has_valid_target:
            hp_pct = ent.hp / max(ent.max_hp, 1) * 100
            faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                           "neutral": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
            lines.append(f"目标: {ent.name} {faction_tag}")
            lines.append(f"  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)  AC {ent.total_ac('chest')}")
            if ent.statuses:
                lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")
        elif terrain == Terrain.WALL:
            lines.append("目标: (墙壁)")
        else:
            lines.append("目标: (空地)")

        # 可见性
        if (oc, oro) in self.state.fov_cache:
            lines.append("可见: 是")
        else:
            lines.append("可见: 否")

        lines.append("")
        lines.append("[[方向键]] 移动光标  [[Enter]] 确认  [[']] 取消")
        return "\n".join(lines[:max_h])

    def _render_target_panel(self) -> str:
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.player_pos

        weapon_name = weapon.name if weapon else "武器"
        reach = weapon.reach if weapon and hasattr(weapon, 'reach') and weapon.reach else 1
        lines = ["── 选择目标格子 ──",
                 f"{weapon_name} → 攻击范围: {reach}格"]

        # 收集范围内格子（与 flow._find_melee_tiles 逻辑一致）
        tiles = []
        for dc in range(-reach, reach + 1):
            for dr in range(-reach, reach + 1):
                if dc == 0 and dr == 0:
                    continue
                tc, tr = pc + dc, pr + dr
                if not self.state.map.within_bounds(tc, tr):
                    continue
                if (tc, tr) not in self.state.fov_cache:
                    continue
                dist = max(abs(dc), abs(dr))
                ent = self.state.get_entity_at(tc, tr)
                if ent is self.state.player:
                    ent = None
                if ent and ent.hp <= 0:
                    ent = None
                tiles.append((dist, tc, tr, ent))
        tiles.sort(key=lambda x: (x[0], x[3] is None))

        for i, (_, tc, tr, ent) in enumerate(tiles[:9]):
            if ent:
                faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                               "neutral": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
                label = f"{ent.name} {faction_tag} HP:{ent.hp}"
            else:
                terrain = self.state.map[tc, tr]
                t_name = {Terrain.WALL: "墙壁", Terrain.DIFFICULT: "灌木", Terrain.PASSABLE: "空地"}.get(terrain, "空地")
                label = t_name
            lines.append(f"[[T{i + 1}]]({tc},{tr}) {label}")
        if len(tiles) > 9:
            lines.append(f"... 还有 {len(tiles) - 9} 个格")
        lines.append("[[T0]]取消")
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
        faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                       "neutral": "[yellow]中立[/]"}.get(c.faction, c.faction)
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


def sell_price_local(price: dict) -> dict:
    """半价收购价（避免循环导入）。"""
    from core.trade import sell_price
    return sell_price(price)


_SPECIAL_ACTIONS_CACHE: list | None = None


def _load_special_actions() -> list:
    """加载特殊行动定义。"""
    global _SPECIAL_ACTIONS_CACHE
    if _SPECIAL_ACTIONS_CACHE is not None:
        return _SPECIAL_ACTIONS_CACHE
    path = os.path.join(_DATA_DIR, "maneuvers.json")
    with open(path, "r", encoding="utf-8") as f:
        _SPECIAL_ACTIONS_CACHE = json.load(f).get("special_actions", [])
    return _SPECIAL_ACTIONS_CACHE
