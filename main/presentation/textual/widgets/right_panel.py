"""右侧面板 —— 默认状态、物品栏、角色面板、观察模式子面板。"""

from textual.widgets import Static

from domain.entity import get_attitude, get_favor
from domain.classes import class_exp_progress, format_class_route_lines
from domain.movement import Terrain, facing_label
from presentation.textual.view_models import GameViewModel
from presentation.textual.widgets.pagination import paginate_lines, to_renderable


class RightPanel(Static):
    view_model: GameViewModel | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # "default" | "inventory" | "character" | "system" | "spellbook"
        # | "quests" | "manual" | "title" | "quest_detail" | "guide"
        self.view_mode = "default"
        self.selected_quest: str = ""    # 任务详情页当前选中的任务名
        self._quests_back: str = "default"  # 任务面板返回目标（default 快捷 / manual 手册进入）
        self._page_offset = 0

    def set_view_model(self, view_model: GameViewModel, *, refresh: bool = True) -> None:
        """接收只读展示快照；state 仅作为旧版复杂面板的兼容桥。"""
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

    def render(self) -> str:
        if self.view_model is None:
            return ""
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
        state = self.view_model.snapshot
        # 物品交互菜单栈优先
        if state.item_menu_stack:
            return self._render_item_menu()
        if state.observe_mode:
            return self._render_observe()
        if self.view_mode == "inventory":
            return self._render_inventory()
        elif self.view_mode == "character":
            return self._render_character()
        elif self.view_mode == "system":
            return self._render_system()
        elif self.view_mode == "spellbook":
            return self._render_spellbook()
        elif self.view_mode == "manual":
            return self._render_manual()
        elif self.view_mode == "title":
            return self._render_title()
        elif self.view_mode == "guide":
            return self._render_guide()
        elif self.view_mode == "quests":
            return self._render_quests()
        elif self.view_mode == "quest_detail":
            return self._render_quest_detail()
        return self._render_default()

    def _render_default(self) -> str:
        p = self.state.controlled_entity
        if p is None:
            return "小队已全灭，旅途结束"
        slow_tag = " [dim]慢速[/]" if self.state.slow_mode else ""
        food_pct = p.food_value * 100 // 15000
        lines = [
            f"[bold]{p.name}[/]  人类 Lv.{p.class_level:.1f} {p.char_class}{slow_tag}",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}  载重 {p.total_carry_weight:.1f}/{p.carry_capacity():.0f}kg  {p.carry_status()['label']}",
            "",
            "[[X]]观察",
            "[[C]]角色面板 [[I]]物品栏 [[B]]法术书 [[E]]思绪",
            "[[Q]]任务 [[Z]]制作 [[K]]烹饪 [[Y]]炼药",
            "[[H]]查看高度 [[M]]地图" if not getattr(self.state, "height_view", False)
            else "[[H]]关闭高度 [[M]]地图",
        ]
        if p.statuses:
            lines.append(f"[red]{' '.join(s.name for s in p.statuses)}[/]")
        return "\n".join(lines)

    def _render_item_menu(self) -> str:
        """渲染物品交互菜单。栈顶决定当前菜单层级。"""
        stack = self.state.item_menu_stack
        if not stack:
            return ""

        top = stack[-1]
        menu_type = top.get("type", "")
        item = top.get("item")
        item_name = item.name if item else "???"
        item_count = getattr(item, 'count', 1) if item else 1

        if menu_type == "item_actions":
            options = top.get("options", [])
            lines = [
                f"[bold]物品: {item_name}[/]",
                f"数量: x{item_count}  {getattr(item, 'description', '')}",
                "",
            ]
            for i, opt in enumerate(options):
                label = opt.get("label", str(i))
                lines.append(f"  [[U{i + 1}]]{label}")
            lines.append("  [[U0]]返回上一级")
            return "\n".join(lines)

        elif menu_type == "quantity_select":
            mode = top.get("mode", "")
            hint = f"[dim]输入 :U数量  如 :U3 丢弃3个[/]"
            max_label = f"可选数量: 1 - {item_count}"
            if mode == "eat":
                if self.state.in_combat:
                    player = self.state.controlled_entity
                    max_qty = min(item_count, player.ap)
                    max_label = f"可选数量: 1 - {max_qty}（剩余AP: {player.ap}）"
                    hint = f"[dim]输入 :U数量  1AP/份  最多 {max_qty} 份[/]"
                else:
                    max_label = f"可选数量: 1 - {item_count}"
                    hint = "[dim]输入 :U数量  1钟摆/份[/]"
            lines = [
                f"[bold]物品: {item_name}[/]",
                max_label,
                "",
                hint,
                "",
                "[[U0]]返回上一级",
            ]
            return "\n".join(lines)

        elif menu_type == "pickup_quantity":
            lines = [
                f"[bold]捡起: {item_name}[/]",
                f"地上数量: x{item_count}",
                "",
                f"[dim]输入 :U数量  如 :U2 捡起2个[/]",
                f"[dim]输入 :U{item_count} 全部捡起[/]",
                "",
                "[[U0]]返回",
            ]
            return "\n".join(lines)

        else:
            return f"[bold]物品: {item_name}[/]\n\n(未知菜单类型: {menu_type})"

    def _render_inventory(self) -> str:
        p = self.state.controlled_entity
        lines = [
            f"[bold]物品栏[/] [dim]I/Esc返回[/]",
            f"金币: {p.gp}GP  饮食: {p.food_value * 100 // 15000}%",
            "── 装备 ──",
        ]
        lines.extend(self._render_equipment_lines(p))
        lines.append("── 背包 ──")
        if p.inventory:
            item_lines = []
            for i, item in enumerate(p.inventory):
                item_lines.append(f"  [{i + 1}] {item.name} x{item.count}")
                if item.description:
                    item_lines.append(f"      {item.description[:20]}")
            lines.extend(item_lines)
        else:
            lines.append("  (空)")
        lines.append("")
        lines.append("[dim]:I序号 装备/使用  :U1-U6 卸除  :W 互换左右手[/]")
        lines.append("[dim][[I]]关闭 [[C]]角色面板 [[X]]观察[/]")
        return "\n".join(lines)

    def _render_character(self) -> str:
        p = self.state.controlled_entity
        progress = class_exp_progress(p.char_class, p.class_exp)
        exp_bar = "+" * int(progress * 10) + "_" * (10 - int(progress * 10))
        lines = [
            f"[bold]角色面板[/] [dim]C/Esc返回[/]  {p.name}  {p.faction}  {p.char_class} Lv.{p.class_level:.1f}",
            f"经验: [{exp_bar}]  总经验 {p.class_exp:.2f}  当前进度 {progress * 100:.0f}%",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}  金币: {p.gp}GP",
            f"载重 {p.total_carry_weight:.1f}/{p.carry_capacity():.0f}kg  [{p.carry_status()['label']}]  饮食: {p.food_value * 100 // 15000}%",
            "",
        ]
        for key, label in [("str", "力量"), ("dex", "敏捷"), ("con", "体质"), ("int", "智力"), ("wis", "感知"), ("cha", "魅力")]:
            val = p.stat(key)
            adj = p.stat_adjust(key)
            sign = "+" if adj >= 0 else ""
            lines.append(f"  {label}: {val} ({sign}{adj})")
        lines.append("")
        lines.append("── 职业路线 ──")
        lines.extend(format_class_route_lines(p))
        lines.append("")
        lines.append("── 装备 ──")
        lines.extend(self._render_equipment_lines(p))
        if p.statuses:
            lines.append(f"[red]状态: {' '.join(s.name for s in p.statuses)}[/]")
        lines.append("")
        lines.append("── 武器与护甲训练 ──")
        for category, label in (
            ("simple", "简易武器"), ("martial", "制式武器"), ("shield", "盾牌"),
        ):
            exp = p.weapon_experience.get(category, 0.0)
            proficiency = p.weapon_proficiency_level(category)
            expertise = p.weapon_expertise_level(category)
            lines.append(
                f"  {label}: [{'+' * proficiency}{'_' * (5 - proficiency)}] "
                f"经验 {exp:.2f}  熟练+{proficiency}  专精+{expertise}"
            )
        for category, label in (
            ("clothing", "服饰"), ("light", "轻甲"),
            ("medium", "中甲"), ("heavy", "重甲"),
        ):
            exp = p.armor_experience.get(category, 0.0)
            proficiency = p.armor_proficiency_level(category)
            expertise = p.armor_expertise_level(category)
            lines.append(
                f"  {label}: [{'+' * proficiency}{'_' * (5 - proficiency)}] "
                f"经验 {exp:.2f}  熟练+{proficiency}  专精+{expertise}"
            )
        lines.append("[dim][[C]]关闭 [[I]]物品栏 [[X]]观察[/]")
        return "\n".join(lines)

    def _render_system(self) -> str:
        """渲染「- 思绪 -」面板。"""
        lines = [
            "[bold]─ 思绪 -[/] [dim]E返回[/]",
            "",
            "  [[E1]]手册",
            "  [[E2]]封存记忆",
            "  [[E3]]回想记忆",
            "  [[E4]]入眠",
            "  [[E5]]主标题",
            "  [[E6]]设置",
            "",
            "[dim]:E序号 选择  E返回[/]",
        ]
        return "\n".join(lines)

    def _render_manual(self) -> str:
        """渲染「手册」面板：称号 / 任务入口。"""
        lines = [
            "[bold]─ 手册 -[/] [dim]E返回[/]",
            "",
            "  [[M1]]称号",
            "  [[M2]]任务",
            "  [[M3]]操作指南",
            "",
            "[dim]:M序号 选择  E返回[/]",
        ]
        return "\n".join(lines)

    def _render_title(self) -> str:
        """渲染「称号」面板。"""
        titles = self.state.controlled_entity.titles
        lines = [
            "[bold]─ 称号 -[/] [dim]E返回[/]",
            "",
        ]
        if titles:
            lines.extend(f"  {title}" for title in titles)
        else:
            lines.append("  (尚未获得称号)")
        lines.extend(["", "[dim]E返回[/]"])
        return "\n".join(lines)

    def _render_guide(self) -> str:
        return (
            "[bold]─ 操作指南 -[/] [dim]E返回[/]\n\n"
            "输入 store 快速存档。输入 read 快速读档。"
        )

    def _render_spellbook(self) -> str:
        """渲染法术书 —— 只记载已知法术本体。"""
        from domain.spell import get_known_spells
        p = self.state.controlled_entity
        known = get_known_spells(p)
        lines = [f"[bold]法术书[/] [dim]B返回[/]", ""]
        if not known:
            lines.append("  (未持有法术书，无可记忆法术)")
            lines.append("  (在物品栏对法术书选择「持有」后记忆)")
            lines.append("")
            lines.append("[dim]:I序号 记忆/取消记忆  B返回[/]")
            return "\n".join(lines)
        for i, s in enumerate(known, 1):
            domain = s.get("domain_cn", s.get("domain", ""))
            lv = s.get("level", 0)
            mp = s.get("mp_cost", 0)
            cast = s.get("cast_time_pendulum", 0)
            cast = f"{s.get('cast_time_ap', 0)} AP/{cast} 钟摆" if s.get("cast_time_ap") else f"{cast} 钟摆"
            components = "、".join(s.get("components", [])) or "无"
            targeting = "需要命中" if s.get("needs_hit") else "不需命中"
            save = s.get("effect", {}).get("save")
            if save:
                targeting += f"，{save} 豁免"
            lines.extend([
                f"  [{i}] {s['name']}  {domain} Lv.{lv}  MP:{mp}  施法:{cast}",
                f"      距离:{s.get('range', 0)}格  成分:{components}  {targeting}",
                f"      描述: {s.get('description', '')}",
                f"      升环: {s.get('upcast', '无')}",
            ])
        lines.append("")
        lines.append("[dim]:I序号 记忆/取消记忆  B返回[/]")
        return "\n".join(lines)

    def _render_quests(self) -> str:
        """任务面板：进行中（可 :Q序号 查看详情）+ 已完成（P1 3.4）。"""
        st = self.state
        from domain.quest import load_quests
        quests = load_quests()
        lines = [f"[bold]任务[/] [dim]E返回[/]", ""]
        lines.append("[bold]进行中[/]")
        active = st.active_quests
        if active:
            for i, name in enumerate(active, 1):
                q = quests.get(name)
                label = q.name if q else name
                lines.append(f"  [Q{i}] {label}（进行中）")
        else:
            lines.append("  (暂无)")
        lines.append("")
        lines.append("[bold]已完成[/]")
        if st.completed_quests:
            for name in st.completed_quests:
                q = quests.get(name)
                label = q.name if q else name
                lines.append(f"  [dim]✓ {label}[/]")
        else:
            lines.append("  (暂无)")
        lines.append("")
        lines.append("[dim]:Q序号 查看详情  E返回[/]")
        return "\n".join(lines)

    def _render_quest_detail(self) -> str:
        """任务详情页：选中任务的完整信息与完成状态。"""
        st = self.state
        from domain.quest import load_quests
        quests = load_quests()
        q = quests.get(self.selected_quest)
        if q is None:
            return "── 任务详情 ──\n\n任务不存在\n\n[E] 返回"
        done = self.selected_quest in st.completed_quests
        status = "[green]已完成[/]" if done else "[yellow]进行中[/]"
        lines = [
            f"[bold]── {q.name} ──[/]  [dim]E返回[/]",
            f"委托人: {q.giver}",
            f"状态: {status}",
            "",
            f"描述: {q.description}",
            f"条件: {'、'.join(q.complete_items) if q.complete_items else '无'}",
            f"报酬: {q.reward_text}",
        ]
        return "\n".join(lines)

    def _render_observe(self) -> str:
        cursor = self.state.observe_cursor
        cx, cy = cursor
        lines = ["[bold]观察模式[/] [dim]X退出 方向键移动光标[/]", ""]

        # 地名 — 从 location_map 哈希表 O(1) 查询，不存在时回退到当前地图名
        loc = self.state.location_map.get(cursor, "")
        if not loc:
            loc = self.state.current_map or ""
        if loc:
            lines.append(f"位置: ({cx}, {cy}) {loc}")
        else:
            lines.append(f"位置: ({cx}, {cy})")

        selected_z, surface = self.state.observation_surface(cursor)
        t_here = surface.terrain if surface.exists else None
        if surface.exists:
            lines.append(f"高度: {selected_z}")
            lines.append(
                f"耐久: {surface.current_durability()}/{surface.max_durability}"
            )
        else:
            lines.append(f"高度: {selected_z}")
            lines.append("地表: 不存在")

        # 特征（地下城入口/出口）
        if t_here == Terrain.STAIRS_DOWN:
            lines.append("特征: 洞口")
        elif t_here == Terrain.STAIRS_UP:
            lines.append("特征: 洞口（出口）")

        # 地形
        terrain = t_here
        t_names = {Terrain.GRASS: "草地", Terrain.BARREN: "荒地", Terrain.PLAIN: "平原", Terrain.FLOOR: "地面", Terrain.STAIRS_DOWN: "楼梯下", Terrain.STAIRS_UP: "楼梯上", Terrain.WATER: "水"}
        if surface.exists:
            lines.append(f"地表: {t_names.get(terrain, '未知')}")

        # 生物；尸体由既有尸体物品逻辑处理，不再显示死亡实体信息
        ent = self.state.get_entity_at(cx, cy, z=selected_z)
        if ent and not ent.is_dead:
            body_type = {
                "human": "人类",
                "humanoid": "类人生物",
                "beast": "野兽",
                "undead": "亡灵",
            }.get(ent.body_type, ent.body_type)
            if ent is self.state.controlled_entity:
                # 玩家自身：显示基础信息与状态（进水后的潮湿等），不显示态度/隐匿
                lines.append(f"生物: {ent.name}(你) Lv.{ent.class_level:.1f}  类型:{body_type}  阵营:{ent.faction}")
                lines.append(f"  朝向: {facing_label(ent.facing)}  HP {ent.hp}/{ent.max_hp}")
                if ent.food_value > 0:
                    lines.append(f"  饮食: {ent.food_value * 100 // 15000}%")
                if ent.statuses:
                    lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")
            else:
                hp_pct = ent.hp / max(ent.max_hp, 1) * 100
                attitude = get_attitude(ent, self.state.controlled_entity)
                att_color = {"敌对": "[red]敌对[/]", "友好": "[green]友好[/]", "冷漠": "[yellow]冷漠[/]"}.get(attitude, attitude)
                favor = get_favor(ent, self.state.controlled_entity)
                lines.append(f"生物: {ent.name} Lv.{ent.class_level:.1f}  类型:{body_type}  阵营:{ent.faction}  态度:{att_color}  好感:{favor}")
                lines.append(f"  朝向: {facing_label(ent.facing)}  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)")
                if ent.food_value > 0:
                    lines.append(f"  饮食: {ent.food_value * 100 // 15000}%")
                if ent.statuses:
                    lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")
                if self.state._is_hidden_to(self.state.controlled_entity, ent, (cx, cy)):
                    lines.append("  目标对你是隐匿的")
        elif ent and ent.is_dead and getattr(ent, "corpse", None):
            corpse = ent.corpse
            lines.append("物品:")
            lines.append(f"  {corpse.name} x{getattr(corpse, 'count', 1)}")
            lines.append(f"  类型: {getattr(corpse, 'item_type', 'misc')}")
            if getattr(corpse, "description", ""):
                lines.append(f"  描述: {corpse.description}")
            lines.append(
                f"  重量: {getattr(corpse, 'weight', 0)}kg  "
                f"耐久: {getattr(corpse, 'durability', 0)}/"
                f"{getattr(corpse, 'max_durability', 0)}  "
                f"堆叠上限: {getattr(corpse, 'stack_limit', 1)}"
            )
            if getattr(corpse, "is_obstacle", False):
                lines.append(
                    f"  障碍类型: {corpse.obstacle_type}  "
                    f"阻挡值: {corpse.block_value}"
                )

        # 背景（地表状态，多状态并列；统一 is_burning/is_wet）
        bg = []
        if self.state.is_burning((cx, cy)):
            bg.append("燃烧")
        if self.state.is_wet((cx, cy)):
            bg.append("潮湿")
        if (cx, cy) in self.state.fog_surfaces:
            bg.append("雾气")
        if bg:
            lines.append(f"背景: {'、'.join(bg)}")

        # 可见度（仅轻度遮蔽——重度遮蔽看不到、不在视野内、观察模式选不到，无需其他档位）
        player_pos = self.state.get_entity_pos(self.state.controlled_entity)
        if player_pos is not None and self.state._cover_level((cx, cy), player_pos[:2]) == "light":
            lines.append("可见度: 轻度遮蔽")

        # 光照
        if cursor in self.state.fov_bright:
            lines.append("亮度: 明亮")
        elif cursor in self.state.fov_dim:
            lines.append("亮度: 微光")
        else:
            lines.append("亮度: 不可见")

        # 物品清单
        from domain.item_actions import get_ground_items_at
        layer_items = [
            (item, position)
            for item, position in self.state.ground_items
            if position[:2] == (cx, cy) and position[2] == selected_z
        ]
        ground_at = get_ground_items_at(layer_items, cx, cy)
        if ground_at:
            lines.append("── 地上物品 ──")
            for g in ground_at:
                lines.append(f"  {g['name']} x{g['count']}  类型:{g['item_type']}")
                if g["description"]:
                    lines.append(f"    描述: {g['description']}")
                lines.append(
                    f"    重量:{g['weight']}kg  耐久:{g['durability']}/{g['max_durability']} "
                    f"堆叠上限:{g['stack_limit']}"
                )
                if g["obstacle_type"]:
                    lines.append(
                        f"    障碍类型:{g['obstacle_type']}  阻挡值:{g['block_value']}"
                    )
                chest_data = getattr(g["item"], "chest_data", None)
                if chest_data is not None:
                    lines.append(
                        f"    箱内物品:{len(chest_data.get('inventory', []))}项 "
                        f"金币:{chest_data.get('gp', 0)} GP"
                    )

        lines.append("[dim][[[] 和 []] 切换高度[/]")
        return "\n".join(lines)

    @staticmethod
    def _render_equipment_lines(player) -> list[str]:
        """构建装备显示行列表（物品栏和角色面板共用）。"""
        slot_groups = [
            [("head", "头部"), ("chest", "躯干"), ("arms", "双臂"), ("legs", "双腿")],
            [("left_hand", "左手"), ("right_hand", "右手")],
            [("spellbook", "法术书")],
        ]
        lines = []
        for group in slot_groups:
            parts = []
            for slot, label in group:
                item = player.equipment.get(slot)
                if item:
                    name = item.name
                    props = getattr(item, 'properties', []) or []
                    if 'two_handed' in props:
                        name += "(双手)"
                    # 火把等光源物品点燃后标注
                    ls = item.light
                    if ls and ls.condition == "lit":
                        name += "（燃烧）"
                    parts.append(f"{label}:{name}")
                elif slot in ("left_hand", "right_hand"):
                    # 空手但另一只手有双手武器 → 标注(双手)
                    other_slot = "right_hand" if slot == "left_hand" else "left_hand"
                    other = player.equipment.get(other_slot)
                    if other:
                        other_props = getattr(other, 'properties', []) or []
                        if 'two_handed' in other_props:
                            parts.append(f"{label}:(双手)")
                            continue
                    parts.append(f"{label}:-")
                else:
                    parts.append(f"{label}:-")
            lines.append("  " + " ".join(parts))
        accessories = getattr(player, "accessories", [])
        lines.append("  饰品:" + (" ".join(item.name for item in accessories) if accessories else "-"))
        return lines
