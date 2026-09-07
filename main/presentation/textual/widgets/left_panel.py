"""左侧面板 —— 探索/战斗默认面板 + 攻击流程子面板（选武器/选目标/选战技/选特殊行动）。"""

import json
import os
from textual.widgets import Static

from domain.movement import Terrain, facing_label
from domain.entity.status import format_status_names
from domain.combat.dual_wield import dual_wield_mode, dual_wield_ap_cost
from domain.actions import collect_actions, available_actions
from domain.classes import combat_abilities
from domain.rest import LONG_REST_PENDULUMS, SHORT_REST_PENDULUMS
from presentation.textual.view_models import GameViewModel
from presentation.textual.widgets.pagination import paginate_lines, to_renderable


def rotation_controls(plane: str, direction: int) -> str:
    """返回瞄准面板的三维旋转状态和快捷键说明。"""
    return (
        f"当前: {plane} 方向: {direction % 8}/8  "
        "1 XY水平旋转  2 XZ横向旋转  3 YZ纵向旋转"
    )

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")


class LeftPanel(Static):
    view_model: GameViewModel | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._action_map: dict[int, tuple] = {}
        self._maneuver_map: dict[int, dict] = {}
        self._special_map: dict[int, str] = {}
        self._cook_map: dict = {}
        self._page_offset = 0
        self._last_identity = None

    def set_view_model(self, view_model: GameViewModel, *, refresh: bool = True) -> None:
        self.view_model = view_model
        if refresh:
            self.refresh()

    def scroll_up(self) -> None:
        self._page_offset = max(0, self._page_offset - 5)
        self.refresh()

    def scroll_down(self) -> None:
        self._page_offset += 5
        self.refresh()

    @property
    def state(self):
        return self.view_model.snapshot if self.view_model is not None else None

    def _panel_identity(self) -> str:
        state = self.state
        if state is None:
            return ""
        iphase = getattr(state, "interact_phase", "") or ""
        if iphase:
            return f"interact:{iphase}"
        return f"combat:{getattr(state, 'combat_phase', 'idle') or 'idle'}"

    def render(self) -> str:
        if self.state is None:
            return ""
        identity = self._panel_identity()
        if self._last_identity is not None and identity != self._last_identity:
            self._page_offset = 0
        self._last_identity = identity
        content = self._build_panel_content()
        try:
            content_region = self.content_region
        except (AttributeError, RuntimeError):
            content_region = None
        if self.size.height <= 0:
            return to_renderable(content)
        height = (
            content_region.height
            if content_region is not None and content_region.height > 0
            else self.size.height
        )
        page, self._page_offset = paginate_lines(
            content.splitlines(),
            height or len(content.splitlines()) or 1,
            self._page_offset,
            from_top=True,
            width=getattr(content_region, "width", 0),
        )
        return to_renderable(page)

    def _build_panel_content(self) -> str:
        """构建未分页的面板内容，避免覆盖 Textual 内部渲染方法。"""
        if self.state is None:
            return ""
        # ── 交互覆盖层（优先级最高）──
        iphase = self.state.interact_phase
        if iphase == "menu":
            return self._render_interact_menu()
        if iphase == "item_menu":
            return self._render_item_interact_panel()
        if iphase == "target":
            return self._render_target_panel()
        if iphase == "looting":
            return self._render_loot_panel()
        if iphase == "trading":
            return self._render_trade_panel()
        if iphase in ("cook_pick", "cook_tool", "cook_confirm",
                      "craft_list", "craft_tool", "craft_product",
                      "craft_continue", "craft_adv_select"):
            return self._render_craft_panel()
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
        if iphase == "reaction":
            return self._render_reaction_panel()
        if iphase == "stealing":
            return self._render_steal_panel()
        if iphase == "steal_caught":
            return self._render_steal_caught_panel()
        if iphase == "party_select":
            return self._render_party_select_panel()
        if iphase == "party_dismiss":
            return self._render_party_dismiss_panel()
        if iphase == "rest_select":
            return self._render_rest_select_panel()
        # ── 攻击流程子面板 — 探索/战斗模式共用 ──
        phase = self.state.combat_phase
        if (self.state.pending_attack or {}).get("target_choice_active"):
            return self._render_target_choice_panel()
        if phase == "select_spell":
            return self._render_spell_panel()
        if phase == "select_cast_attr":
            return self._render_cast_attr_panel()
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

    def _render_reaction_panel(self) -> str:
        st = self.state
        if not st.pending_reactions:
            return "[dim]无可反应[/]"
        ev = st.pending_reactions[-1]
        mover = ev.get("mover") or ev.get("attacker")
        p = st.controlled_entity
        from domain.combat.opportunity import REACTION_DEFS, default_melee_weapon, weapon_ap_cost, list_available_reactions
        spec = REACTION_DEFS.get(ev["kind"], REACTION_DEFS["opportunity_attack"])
        lines = [
            f"[bold]── {spec['panel_title']} ──[/]",
            f"触发者: {mover.name}",
            "",
        ]
        idx = 1
        for item in list_available_reactions(p, ev["kind"]):
            if item["kind"] == "opportunity_attack":
                weapon = default_melee_weapon(p)
                cost = weapon_ap_cost(weapon)
                lines.append(f"[[A{idx}]]{item['name']}  AP:{cost}")
            elif item["kind"] == "shield":
                lines.append(f"[[A{idx}]]{item['name']}")
            idx += 1
        lines.extend(["[[']]取消"])
        return "\n".join(lines)

    def _knockout_line(self) -> str:
        """击晕/杀害模式切换键文案（阶段9）：击晕模式→切换杀害，杀害模式→切换击晕。"""
        mode = getattr(self.state, 'knockout_mode', False)
        if mode:
            return "[[F]]切换杀害"
        return "[[F]]切换击晕"

    def _render_explore_default(self) -> str:
        return "\n".join(self._party_lines() + [
            self._combat_mode_line(),
            "[[0]]交互 [[N]]动作",
            "[[g]]慢速 [[G]]疾走  [[r]]短休 [[R]]长休  [[,]]消磨",
            "[[A]]攻击 [[S]]法术  " + self._knockout_line(),
            self._stealth_line(),
            r"] 向高处攀爬  \[ 向低处攀爬  L 松手",
            "[[;]]多选成员移动",
            "[[O]]遣散成员",
            "[[D1]]北 [[D2]]东 [[D3]]南 [[D4]]西",
        ])

    def _render_combat_default(self) -> str:
        p = self.state.controlled_entity
        # 阶段7.6：AP%化（固定10格），右侧显示"剩余AP/上限"
        filled = max(0, min(10, round(p.ap / max(p.max_ap, 1) * 10)))
        lines = self._party_lines() + [
            self._combat_mode_line(),
            f"AP [{'|' * filled}{'.' * (10 - filled)}] {p.ap}/{p.max_ap}",
            "S-Tab 结束轮转回合",
            "[[0]]交互 [[N]]动作",
            "[[g]]慢速 [[G]]疾走  [[r]]短休 [[R]]长休  [[,]]消磨",
            "[[A]]攻击 [[S]]法术  " + self._knockout_line(),
            self._stealth_line(),
            r"] 向高处攀爬  \[ 向低处攀爬  L 松手",
            "[[O]]遣散成员",
            "[[D1]]北 [[D2]]东 [[D3]]南 [[D4]]西",
        ]
        return "\n".join(lines)

    def _combat_mode_line(self) -> str:
        if self.state.in_combat:
            status = "参战中" if self.state.is_engaged() else "未参战"
            return f"[[T]]探索模式（{status}）"
        return "[[T]]轮转模式"

    def _party_lines(self) -> list[str]:
        """显示固定四个小队槽位；宽度不足时按列自动换行。"""
        members = list(getattr(self.state, "party", []))[:4]
        slots = []
        for index in range(4):
            member = members[index] if index < len(members) else None
            if member is None:
                slots.append(["空位", "HP --/--", "MP --/--", "TEN --/--"])
                continue
            status = "（死亡）" if member.is_dead else ""
            slots.append([
                f"{member.name}{status}",
                f"HP {member.hp}/{member.max_hp}",
                f"MP {member.mp}/{member.max_mp}",
                f"TEN {member.tenacity}/{member.tenacity_cap()}",
            ])

        width = getattr(getattr(self, "content_region", None), "width", 0)
        width = width or self.size.width or 68
        slot_width = max(len(line) for slot in slots for line in slot) + 2
        columns = max(1, min(4, width // slot_width))
        lines = []
        for start in range(0, 4, columns):
            row_slots = slots[start:start + columns]
            for line_index in range(4):
                lines.append("  ".join(
                    slot[line_index].ljust(slot_width - 2)
                    for slot in row_slots
                ).rstrip())
        lines.append("─" * max(1, min(width, columns * slot_width + (columns - 1) * 2)))
        return lines

    def _stealth_line(self) -> str:
        """隐匿提示行：当前控制的实体对谁隐匿。"""
        p = self.state.controlled_entity
        hidden = self.state._hidden_target_names(p)
        if hidden:
            return f"隐匿: 对{', '.join(hidden)}"
        return "隐匿: 无"

    def _render_action_menu(self) -> str:
        """动作子面板：扫描实体 actions 动态生成（D22）。"""
        actions = available_actions(self.state.controlled_entity)
        lines = ["[bold]── 动作 ──[/]", ""]
        for i, a in enumerate(actions, 1):
            name = a.get("name", a.get("key", "?"))
            cost_ap = a.get("cost_ap", 0)
            cost_p = a.get("cost_pendulum", 0)
            if a.get("key") == "stand":
                prone = self.state.controlled_entity.has_status("prone")
                hiding = self.state.controlled_entity.has_status("hiding")
                cost_ap = 30 if prone else 20
                cost_p = 3 if prone else 2
            lines.append(f"[[N{i}]]{name}  AP:{cost_ap} 钟摆:{cost_p}")
        lines.append("")
        lines.append("[[']]取消")
        return "\n".join(lines)

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
            "[[']]取消",
        ])

    def _render_party_select_panel(self) -> str:
        """多选小队成员移动面板。"""
        st = self.state
        lines = ["[bold]── 选择同行成员 ──[/]", ""]
        controlled = st.controlled_entity
        members = [m for m in st.party if not m.is_dead]
        for idx in range(4):
            if idx >= len(members):
                lines.append(f"[[{idx + 1}]] 空位")
                continue
            member = members[idx]
            current_mark = " (当前)" if member is controlled else ""
            selected = id(member) in st.selected_party_members
            mark = "✓" if selected else " "
            lines.append(f"[[{idx + 1}]] [{mark}] {member.name}{current_mark}")
        lines.extend(["", "[[Enter]]确认  [[']]取消"])
        return "\n".join(lines)

    def _render_party_dismiss_panel(self) -> str:
        """遣散小队成员面板。列出全部槽位（含死者）；当前受控者不可勾选。"""
        st = self.state
        lines = ["[bold]── 遣散成员 ──[/]", ""]
        controlled = st.controlled_entity
        members = list(st.party)
        selected = getattr(st, "selected_dismiss_members", set())
        for idx in range(4):
            if idx >= len(members):
                lines.append(f"[[{idx + 1}]] 空位")
                continue
            member = members[idx]
            current_mark = " (当前)" if member is controlled else ""
            mark = "✓" if id(member) in selected else " "
            lines.append(f"[[{idx + 1}]] [{mark}] {member.name}{current_mark}")
        lines.extend(["", "[[Enter]]遣散  [[']]取消"])
        return "\n".join(lines)

    def _render_rest_select_panel(self) -> str:
        """短休/长休多选成员面板。"""
        st = self.state
        kind = "短休" if st.pending_rest_kind == "short" else "长休"
        duration = SHORT_REST_PENDULUMS if st.pending_rest_kind == "short" else LONG_REST_PENDULUMS
        lines = [f"[bold]── 选择一同{kind}的成员 ──[/]", f"{duration} 钟摆", ""]
        controlled = st.controlled_entity
        members = [m for m in st.party if not m.is_dead]
        for idx in range(4):
            if idx >= len(members):
                lines.append(f"[[{idx + 1}]] 空位")
                continue
            member = members[idx]
            current_mark = " (当前)" if member is controlled else ""
            engaged = st.is_engaged(member)
            selected = id(member) in st.selected_rest_members
            mark = "✓" if selected else " "
            extra = " 参战" if engaged else ""
            lines.append(f"[[{idx + 1}]] [{mark}] {member.name}{current_mark}{extra}")
        lines.extend(["", "[[Enter]]确认  [[']]取消"])
        return "\n".join(lines)


    # ── 动作收集（数据与渲染分离）──


    def _render_action_panel(self) -> str:
        actions = collect_actions(self.state)
        # CombatFlow 持有该字典的同一引用；原地更新，避免渲染后替换引用导致流程仍使用空映射。
        self._action_map.clear()
        title = "── 选择攻击方式 ──"
        player = self.state.controlled_entity
        if getattr(player, "pending_tenacity_bonus", 0):
            title += " 连击"
        lines = [title]
        for i, a in enumerate(actions, 1):
            self._action_map[i] = (a["mode"], a["weapon"])
            lines.append(f"[[A{i}]]{a['label']}")
        self._action_map[0] = ("cancel", None)
        lines.append("[[']]取消")
        return "\n".join(lines)

    def _render_spell_panel(self) -> str:
        """选择施放法术面板 —— 显示已记忆法术 + 法术位占用。"""
        from domain.spell import get_memorized_spells, get_spell_slots
        p = self.state.controlled_entity
        memorized = get_memorized_spells(p)
        slots = get_spell_slots(p)
        total_slots = sum(slots.values())
        used = len(memorized)
        lines = ["── 选择法术 ──", f"法术位: {used}/{total_slots}", ""]
        for i, s in enumerate(memorized, 1):
            mp = s.get("mp_cost", 0)
            ap = s.get("cast_time_ap", 0)
            rng = s.get("range", 0)
            rng_str = f"射程:{rng}" if rng > 0 else "自身"
            lines.append(f"[[A{i}]]{s['name']}  MP:{mp}  AP:{ap}  {rng_str}")
        for i in range(used + 1, total_slots + 1):
            lines.append(f"[[A{i}]](空位)")
        lines.append("[[']]取消")
        return "\n".join(lines)

    _STAT_LABELS = {"str": "力量", "dex": "敏捷", "con": "体质", "int": "智力", "wis": "感知", "cha": "魅力"}

    def _render_cast_attr_panel(self) -> str:
        """多属性法术：选择施法属性面板。"""
        from domain.spell import spell_attributes
        spell = getattr(self.state, 'pending_spell', None) or {}
        attrs = spell_attributes(spell)
        lines = ["── 选择施法属性 ──", f"法术: {spell.get('name', '?')}", ""]
        for i, a in enumerate(attrs, 1):
            label = self._STAT_LABELS.get(a, a)
            lines.append(f"[[A{i}]]{label}")
        lines.append("[[']]取消")
        return "\n".join(lines)

    def _render_aim_panel(self) -> str:
        """通用瞄准面板（近战/远程/法术/投掷/点火）。只看范围，不看视野。"""
        pa = self.state.pending_attack or {}
        weapon = pa.get("weapon")
        pc, pr = self.state.controlled_entity_pos[:2]
        oc, oro = self.state.observe_cursor
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
        # 多格形状：光标 = 锚格 + 形状偏移
        from domain.combat.shape import shape_cells, shape_from_pending_attack
        shape = shape_from_pending_attack(pa)
        target_z = int(pa.get("target_z", self.state.controlled_entity.z))
        anchor = (oc, oro, target_z)
        cells = shape_cells(anchor, shape)
        multi = not shape.is_single

        # 距离：多格取最远格
        far = max(max(abs(c - pc), abs(r - pr)) for c, r, *_ in cells)
        in_range = far <= max_range

        # 地表（锚格）
        target_z = int(pa.get("target_z", self.state.controlled_entity.z))
        target_surface = self.state.surface_at((oc, oro), target_z, create=False)
        terrain = target_surface.terrain
        t_names = {Terrain.GRASS: "草地", Terrain.BARREN: "荒地", Terrain.PLAIN: "平原", Terrain.FLOOR: "地面", Terrain.STAIRS_DOWN: "楼梯下", Terrain.STAIRS_UP: "楼梯上", Terrain.WATER: "水"}
        terrain_name = t_names.get(terrain, "未知")

        # 目标：范围允许即可选（含自身，不校验视野）
        is_revive = pa.get("spell", {}).get("effect", {}).get("type") == "revive"
        ent = self.state.get_entity_at(oc, oro, target_z)
        has_valid_target = ent and (not ent.is_dead or is_revive)
        ground = next(
            (item for item, pos in self.state.ground_items
             if pos[:2] == (oc, oro)
             and (len(pos) < 3 or pos[2] == target_z)),
            None,
        )

        lines = [
            "[bold]── 瞄准 ──[/]",
            f"{target_label}  范围: {max_range}格",
        ]
        if multi:
            rows = max(r for _, r, *_ in shape.offsets) + 1
            cols = max(c for c, *_ in shape.offsets) + 1
            depth = max(offset[2] for offset in shape.offsets) + 1 if len(
                shape.offsets[0]
            ) == 3 else 1
            plane = pa.get("target_rotation_plane", "XY")
            direction = pa.get("target_rotation", 0)
            lines.append(f"形状: {cols}x{rows}x{depth}  光标: {len(cells)}格")
            lines.append(rotation_controls(plane, direction))
        lines.append(f"光标: ({oc}, {oro})  距离: {far}/{max_range}"
                     + (" [green]✓[/]" if in_range else " [red]超出范围[/]"))
        lines.append(f"地表: {terrain_name}  高度: {target_z}")
        lines.append("")

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

        if multi:
            parts = []
            for c, r, cell_z in cells:
                e = self.state.get_entity_at(c, r, z=cell_z)
                parts.append(e.name if e and not e.is_dead else "空地")
            lines.append("目标: " + ", ".join(parts))
        elif has_valid_target:
            if ent.is_dead:
                lines.append(f"目标: {ent.name} (尸体)")
            else:
                hp_pct = ent.hp / max(ent.max_hp, 1) * 100
                self_tag = " (你)" if ent is self.state.controlled_entity else ""
                faction_tag = {"混乱": "[red]敌对[/]", "守序": "[green]友好[/]",
                               "中立": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
                lines.append(f"目标: {ent.name}{self_tag} {faction_tag}")
                lines.append(f"  朝向: {facing_label(ent.facing)}  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)  AC {ent.total_ac('chest')}")
                if ent.statuses:
                    lines.append(f"  状态: {', '.join(format_status_names(ent))}")
        elif ground is not None:
            obstacle = getattr(ground, "obstacle_type", "")
            obstacle_name = getattr(obstacle, "value", obstacle) or "无"
            lines.append(f"目标: {ground.name}")
            lines.append(
                f"  障碍: {obstacle_name}  耐久: "
                f"{getattr(ground, 'durability', 0)}/{getattr(ground, 'max_durability', 0)}"
                f"  阻挡值: {getattr(ground, 'block_value', 0)}"
            )
        else:
            lines.append("目标: (空地)")

        lines.append("")
        rotate_tip = "  [[1]][[2]][[3]]选择旋转平面" if multi else ""
        lines.append(
            f"[[方向键]] 移动光标  [[ / ]]调整高度  [[Enter]] 确认  "
            f"[[']] 取消{rotate_tip}"
        )
        return "\n".join(lines)

    def _render_target_choice_panel(self) -> str:
        """同格多目标选择面板。"""
        pa = self.state.pending_attack or {}
        position = pa.get("target_choice_position", (0, 0))
        lines = [
            "[bold]── 选择目标 ──[/]",
            f"位置: ({position[0]}, {position[1]})",
            "",
        ]
        for index, target in enumerate(pa.get("target_candidates", []), 1):
            if target is None:
                label = "空气"
                detail = "无目标"
            elif hasattr(target, "hp"):
                label = target.name
                detail = f"HP {target.hp}/{target.max_hp}"
            elif hasattr(target, "durability"):
                label = target.name
                detail = f"耐久 {target.durability}/{target.max_durability}"
            else:
                label = getattr(target, "name", str(target))
                detail = ""
            lines.append(f"[[A{index}]]{label}  {detail}")
        lines.extend(["", "[[']]取消"])
        return "\n".join(lines)

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

        maneuvers = combat_abilities(
            self.state.controlled_entity, "maneuver", target, weapon,
            self.state.controlled_entity_pos[:2], pa.get("target_pos"))
        self._maneuver_map.clear()
        lines = ["── 命中后选择战技 ──",
                 f"{weapon.name if weapon else '武器'}击中{target_name} (roll={attack_roll} vs AC={target_ac})"]
        for i, m in enumerate(maneuvers, 1):
            self._maneuver_map[i] = m
            desc = m.get('effect', '')
            if desc == 'damage_bonus':
                desc_text = f'伤害+{m["value"]}'
            elif desc == 'damage_multiplier':
                desc_text = m.get('desc', '伤害翻倍')
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
        p = self.state.controlled_entity
        lower_actions = combat_abilities(
            p, "lower", target, weapon, self.state.controlled_entity_pos[:2],
            pa.get("target_pos"))

        target_name = target.name if target else "目标"
        target_ac = target.total_ac('chest') if target else 0

        self._special_map.clear()
        lines = ["── 未命中后选择下位动作 ──",
                 f"{weapon.name if weapon else '武器'}挥空{target_name} (roll={attack_roll} vs AC={target_ac})"]
        for i, action in enumerate(lower_actions, 1):
            self._special_map[i] = action["name"]
            lines.append(f"[[A{i}]]{action['name']}  AP+{action['ap_extra']}")
        self._special_map[0] = None
        lines.append("[[']]取消")
        return "\n".join(lines)


    # ── 交互覆盖层子面板 ──

    def _render_interact_menu(self) -> str:
        """交互目标选择菜单。"""
        targets = self.state.interact_targets
        lines = ["[bold]── 交互 ──[/]", ""]
        for i, t in enumerate(targets, 1):
            lines.append(f"[[{i}]]{t.label}")
        lines.append("")
        lines.append("[[']]取消")
        return "\n".join(lines)

    def _render_item_interact_panel(self) -> str:
        target = self.state.interact_target
        if target is None:
            return "── 物品 ──\n\n(无目标)\n\n[[']]取消"
        items = target.extra.get("items", [])
        lines = [f"[bold]── {target.label} ──[/]", ""]
        from presentation.textual.controllers.craft import item_quality_label
        for item in items:
            obstacle = getattr(getattr(item, "obstacle_type", None), "value",
                               getattr(item, "obstacle_type", None))
            durability = f"耐久 {item.durability}/{item.max_durability}"
            suffix = f"  障碍:{obstacle}" if obstacle else ""
            lines.append(f"{item_quality_label(item)} x{item.count}  {durability}{suffix}")
        from domain.interact import item_interact_options
        options = item_interact_options(self.state, target)
        if options:
            lines.append("")
        for index, (_action, label) in enumerate(options, 1):
            lines.append(f"[[{index}]]{label}")
        if not options:
            lines.extend(["", "该物品不可捡起"])
        lines.append("[[']]取消")
        return "\n".join(lines)

    def _render_target_panel(self) -> str:
        """对象个人交互面板：名称、态度、阵营，选项并列。"""
        from domain.faction import get_attitude
        from domain.interact import creature_interact_options
        target = self.state.interact_target
        if target is None or target.creature is None:
            return "── 【？】 ──\n\n(无目标)\n\n[[']]取消"
        creature = target.creature
        player = self.state.controlled_entity
        lines = [f"[bold]── 【{creature.name}】 ──[/]", ""]
        attitude = get_attitude(creature, player) if player is not None else ""
        info = f"阵营 {creature.faction}"
        if attitude:
            info = f"态度 {attitude}  {info}"
        lines.append(info)
        lines.append("")
        for index, (_action, label) in enumerate(
            creature_interact_options(self.state, creature), 1
        ):
            lines.append(f"[[{index}]]{label}")
        lines.append("[[']]取消")
        return "\n".join(lines)

    def _render_loot_panel(self) -> str:
        """搜刮面板：勾选后回车拿走。"""
        from domain.loot import list_loot_entries
        target = getattr(self.state, "interact_target", None)
        creature = target.creature if target else None
        if creature is None:
            return "── 搜刮 ──\n\n(目标已离开)\n\n[[']]取消"
        selected = getattr(self.state, "loot_selected", set())
        lines = [f"[bold]── 搜刮 {creature.name} ──[/]", ""]
        entries = list_loot_entries(creature)
        if not entries:
            lines.append("(空)")
        for index, entry in enumerate(entries, 1):
            mark = "✓" if entry["id"] in selected else " "
            lines.append(f"[[L{index}]] [{mark}] {entry['label']}")
        lines.extend(["", ":L序号 选择  [[Enter]]拿走  [[']]取消"])
        return "\n".join(lines)

    def _render_steal_panel(self) -> str:
        """偷窃物品选择面板（P1 3.3）。"""
        from domain.trade import price_to_text
        st = self.state
        target = st.steal_target
        if target is None:
            return "── 偷窃 ──\n\n(目标已离开)\n\n[[']]取消"
        lines = [f"[bold]── 偷窃 {target.name} ──[/]", ""]
        if st.steal_stolen:
            lines.append(f"已偷到: {', '.join(i.name for i in st.steal_stolen)}")
            lines.append("")
        inv = target.inventory
        if inv:
            for i, it in enumerate(inv, 1):
                lines.append(f"[[S{i}]]{it.name}  {price_to_text(it.price)}")
        else:
            lines.append("  (身上空无一物)")
        lines.append("")
        lines.append("[:S序号] 偷窃  [[']]取消")
        return "\n".join(lines)

    def _render_steal_caught_panel(self) -> str:
        """被发现对话面板：同意/否决/游说/威胁/欺瞒。"""
        st = self.state
        target = st.steal_target
        tname = target.name if target else "对方"
        lines = [
            f"[bold]── {tname} 要求归还物品 ──[/]",
            "",
            "[[1]]同意归还",
            "[[2]]否决（敌对）",
            "[[3]]游说",
            "[[4]]威胁（未实装）",
            "[[5]]欺瞒（未实装）",
            "",
            "[:S序号] 选择  [[']]取消",
        ]
        return "\n".join(lines)

    def _render_trade_panel(self) -> str:
        """交易面板：商店库存 + 玩家背包。动态反映库存变化。"""
        from domain.trade import (shop_gold_text, price_to_text, copper_to_currency,
                                 player_wealth_copper, DEFAULT_STOCK_QTY)

        shop = self.state.shop_data
        p = self.state.controlled_entity
        if shop is None:
            return "── 交易 ──\n\n商店数据异常\n\n[[']]取消"

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
        lines.append(":B序号 购买  :S序号 出售  [[']]取消")
        return "\n".join(lines)


    # ── 烹饪 / 制作 / 炼药 ──

    def _render_craft_panel(self) -> str:
        from presentation.textual.controllers.craft import item_info_text
        from domain.craft.recipe import (
            HANDS,
            effective_required,
            make_recipe_by_output,
            match_from_materials,
            time_for_tool,
        )

        ip = self.state.interact_phase
        data = getattr(self.state, "pending_craft", {}) or {}
        kind = data.get("kind", "cook")
        titles = {"cook": "烹饪", "alchemy": "炼药", "make": "制作"}
        title = titles.get(kind, "制作")
        if ip == "cook_pick":
            lines = [f"[bold]── {title}：选择材料 ──[/]", ""]
            names = data.get("pick_names") or []
            pick = data.get("pick") or {}
            prefix = "Y" if kind == "alchemy" else "K"
            for i, name in enumerate(names, 1):
                lines.append(f"[[{prefix}{i}]]{item_info_text(name)}")
            if pick:
                lines.append("")
                lines.append("已选: " + " ".join(f"{n}x{c}" for n, c in pick.items()))
            lines.append(f"已选 {sum(pick.values())}/5 份")
            lines.append("回车下一层  ' 退出")
            return "\n".join(lines)
        if ip == "cook_tool" or ip == "craft_tool":
            prefix = "Z" if kind == "make" else ("Y" if kind == "alchemy" else "K")
            from domain.craft.stations import available_tools
            pos = self.state.controlled_entity_pos
            backpack = ("皮革工具",) if kind == "make" else (
                ("捣药钵",) if kind == "alchemy" else ()
            )
            tools = available_tools(self.state, pos, backpack)
            lines = [f"[bold]── {title}：选择工具 ──[/]", ""]
            for i, name in enumerate(tools, 1):
                mark = " *" if name == data.get("tool") else ""
                lines.append(f"[[{prefix}{i}]]{name}{mark}")
            back = "返回成品列表" if kind == "make" else "返回材料"
            lines.append(f"回车确认  ' {back}")
            return "\n".join(lines)
        if ip == "cook_confirm":
            pick = data.get("pick") or {}
            tool = data.get("tool", HANDS)
            lines = [f"[bold]── {title}：确认 ──[/]", ""]
            for name, count in pick.items():
                lines.append(f"  {item_info_text(name, count)}")
            lines.append(f"工具: {tool}")
            try:
                recipe = match_from_materials(kind, pick, tool)
            except ValueError:
                lines.append("没有匹配的配方")
            else:
                out_name, out_count = recipe.output
                lines.append(f"产出: {item_info_text(out_name, out_count)}")
                lines.append("所需材料:")
                for mat, qty in effective_required(recipe, tool).items():
                    lines.append(f"  {item_info_text(mat, qty)}")
                lines.append(f"所需时间: {time_for_tool(recipe, tool)} 钟摆")
            lines.append("回车执行  ' 返回工具")
            return "\n".join(lines)
        if ip == "craft_list":
            lines = ["[bold]── 制作：成品列表 ──[/]", ""]
            from domain.craft.recipe import BY_CRAFT
            player = self.state.controlled_entity
            idx = 1
            for recipe in BY_CRAFT.get("make", ()):
                if recipe.id in player.known_recipes:
                    lines.append(f"[[Z{idx}]]{item_info_text(recipe.output[0], recipe.output[1])}")
                    idx += 1
            if idx == 1:
                lines.append("  (没有已知制作表)")
            lines.append("' 退出")
            return "\n".join(lines)
        if ip == "craft_product":
            name = data.get("product", "")
            recipe = make_recipe_by_output(name)
            tool = data.get("tool") or HANDS
            lines = ["[bold]── 制作：成品 ──[/]", "", item_info_text(name)]
            lines.append("材料:")
            for mat, qty in recipe.required.items():
                lines.append(f"  {item_info_text(mat, qty)}")
            lines.append(f"所需时间: {time_for_tool(recipe, tool)} 钟摆")
            lines.append(f"工具: {tool}")
            lines.append(":Z钟摆数 开始  ' 返回工具")
            return "\n".join(lines)
        if ip == "craft_continue":
            lines = [
                "[bold]── 继续制作 ──[/]",
                "",
                data.get("continue_name", ""),
                f"已做/所需: {data.get('continue_progress', 0)}/{data.get('continue_required', 0)}",
                ":Z钟摆数  ' 退出",
            ]
            return "\n".join(lines)
        rolls = data.get("rolls") or []
        lines = ["── 优势! 选择点数 ──"]
        for i, face in enumerate(rolls, 1):
            lines.append(f"  [[{i}]] {face}")
        lines.append("输入序号选择其中一个点数")
        return "\n".join(lines)


    def _render_chest_panel(self) -> str:
        """箱子交互面板：拿取区 + 存放区。"""
        target = getattr(self.state, 'interact_target', None)
        if target is None:
            return "── 箱子 ──\n\n(数据异常)\n\n[[']]取消"

        chest_data = target.extra.get("chest_data", {})
        label = chest_data.get("label", "箱子")
        gp = chest_data.get("gp", 0)
        chest_inv = chest_data.get("inventory", [])
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
        player_inv = self.state.controlled_entity.inventory
        if player_inv:
            for i, item in enumerate(player_inv, 1):
                count_str = f" x{item.count}" if item.count > 1 else ""
                lines.append(f"  [[S{i}]]{item.name}{count_str}")
        else:
            lines.append("  (背包为空)")
        lines.append("")

        lines.append(":C序号 拿取  :S序号 存放  [[']]取消")
        return "\n".join(lines)

    def _render_chest_qty_panel(self, mode: str) -> str:
        """箱子数量选择面板。mode: "take" | "store" """
        target = getattr(self.state, 'interact_target', None)
        if target is None:
            return "── 箱子 ──\n\n(数据异常)\n\n[[']]取消"
        extra = target.extra
        item = extra.get("_qty_item")
        max_qty = extra.get("_qty_max", 1)
        if item is None:
            return "── 箱子 ──\n\n(数据异常)\n\n[[']]取消"
        action = "拿取" if mode == "take" else "存放"
        prefix = "C" if mode == "take" else "S"
        return "\n".join([
            f"[bold]── {action} {item.name} ──[/]",
            f"可选: 1 - {max_qty}",
            "",
            f"输入 :{prefix}数量 确认  [[']]取消",
        ])


def sell_price_local(price: dict) -> dict:
    """半价收购价（避免循环导入）。"""
    from domain.trade import sell_price
    return sell_price(price)


