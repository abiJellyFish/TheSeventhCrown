"""左侧面板 —— 探索/战斗默认面板 + 攻击流程子面板（选武器/选目标/选战技/选特殊行动）。"""

import json
import os
from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain

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

    def _render_action_panel(self) -> str:
        p = self.state.player
        left = p.equipment.get("left_hand")
        right = p.equipment.get("right_hand")
        self._action_map = {}

        lines = ["── 选择攻击方式 ──"]
        idx = 1

        if left:
            if hasattr(left, 'weapon_type'):
                self._action_map[idx] = ("left_hand", left)
                lines.append(f"[[A{idx}]]左手武器  {left.name} {left.damage} {left.damage_type} AP:{left.ap_cost}")
            else:
                self._action_map[idx] = ("left_hand_blocked", left)
                lines.append(f"[[A{idx}]]左手武器  {left.name} (不能攻击)")
            idx += 1
        if right:
            if hasattr(right, 'weapon_type'):
                self._action_map[idx] = ("right_hand", right)
                lines.append(f"[[A{idx}]]右手武器  {right.name} {right.damage} {right.damage_type} AP:{right.ap_cost}")
            else:
                self._action_map[idx] = ("right_hand_blocked", right)
                lines.append(f"[[A{idx}]]右手武器  {right.name} (不能攻击)")
            idx += 1
        if left and hasattr(left, 'weapon_type') and right and hasattr(right, 'weapon_type'):
            self._action_map[idx] = ("dual_wield", right)
            lines.append(f"[[A{idx}]]双持武器  {left.name}+{right.name} AP:3")
            idx += 1
        if right and hasattr(right, 'weapon_type') and right.weapon_type == "melee":
            self._action_map[idx] = ("two_hand", right)
            lines.append(f"[[A{idx}]]双手并用  {right.name} 命中+1 伤害+2 AP:{right.ap_cost}")
            idx += 1

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
        lines.append("[[方向键]] 移动光标  [[Enter]] 确认  [[Esc]] 取消")
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
        """交易面板：商店库存 + 玩家背包。"""
        from core.trade import shop_gold_text, price_to_text

        shop = self.state.shop_data
        p = self.state.player
        max_h = self.size.height

        if shop is None:
            return "── 交易 ──\n\n商店数据异常\n\n[[0]]离开"

        shop_name = shop.get("name", "商店")
        lines = [
            f"[bold]── 交易 ── {shop_name}[/]  资金: {shop_gold_text(shop)}",
            f"你的金币: {p.gp}GP {p.sp}SP {p.cp}CP",
            "",
            "[bold]商店库存[/]",
        ]

        # 商店库存
        stock = shop.get("_resolved_stock", [])
        for i, entry in enumerate(stock, 1):
            item = entry["item"]
            price_text = price_to_text(entry["price"])
            lines.append(f"[[B{i}]]{item.name}  {price_text}")
        if not stock:
            lines.append("  (已售罄)")

        lines.append("")
        lines.append("[bold]你的背包[/]")

        # 玩家背包（只显示可出售的物品，不显示已装备的）
        equip_names = set()
        for slot_name, equip_item in p.equipment.items():
            if equip_item is not None:
                equip_names.add(equip_item.name)
                # 也记录 id，同一类型物品可能有多件
        inv_idx = 0
        shown = 0
        for item in p.inventory:
            inv_idx += 1
            # 如果已被装备，跳过
            # (简化：通过名称判断；同名人可能有两件，只跳第一件装备的。TODO 后续用 id)
            sell_p = sell_price_local(item.price)
            lines.append(f"[[S{shown + 1}]]{item.name} x{item.count}  售价:{price_to_text(sell_p)}")
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
