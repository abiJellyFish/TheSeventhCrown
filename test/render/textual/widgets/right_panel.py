"""右侧面板 —— 默认状态、物品栏、角色面板、观察模式子面板。"""

from textual.widgets import Static

from core.game_state import GameState
from core.entity import get_attitude
from core.movement import Terrain, facing_label


class RightPanel(Static):
    state: GameState | None = None
    view_mode: str = "default"  # "default" | "inventory" | "character" | "system" | "spellbook"

    def render(self) -> str:
        if self.state is None:
            return ""
        # 物品交互菜单栈优先
        if self.state.item_menu_stack:
            return self._render_item_menu()
        if self.state.observe_mode:
            return self._render_observe()
        if self.view_mode == "inventory":
            return self._render_inventory()
        elif self.view_mode == "character":
            return self._render_character()
        elif self.view_mode == "system":
            return self._render_system()
        elif self.view_mode == "spellbook":
            return self._render_spellbook()
        return self._render_default()

    def _render_default(self) -> str:
        p = self.state.player
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
            "[[Z]]制作 [[K]]烹饪 [[Y]]炼药",
            "[[H]]高度 [[M]]地图",
        ]
        if p.statuses:
            lines.append(f"[red]{' '.join(s.name for s in p.statuses)}[/]")
        return "\n".join(lines)

    def _render_item_menu(self) -> str:
        """渲染物品交互菜单。栈顶决定当前菜单层级。"""
        max_h = self.size.height
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
            return "\n".join(lines[:max_h])

        elif menu_type == "quantity_select":
            mode = top.get("mode", "")
            hint = f"[dim]输入 :U数量  如 :U3 丢弃3个[/]"
            max_label = f"可选数量: 1 - {item_count}"
            if mode == "eat":
                if self.state.in_combat:
                    player = self.state.player
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
            return "\n".join(lines[:max_h])

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
            return "\n".join(lines[:max_h])

        else:
            return f"[bold]物品: {item_name}[/]\n\n(未知菜单类型: {menu_type})"

    def _render_inventory(self) -> str:
        p = self.state.player
        # DEBUG 仅测试：背包为空时打印诊断，定位后移除
        if p is not None and not p.inventory:
            import traceback
            with open("D:/桌面/ttt/debug_empty_inv.log", "a", encoding="utf-8") as f:
                f.write(f"empty inv: name={p.name} hp={p.hp} food={p.food_value} ctrl={p.controlled} eq={p.equipment['right_hand'].name if p.equipment.get('right_hand') else 'None'}\n")
        max_h = self.size.height
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
            available = max_h - len(lines) - 3
            if available >= len(item_lines):
                lines.extend(item_lines)
            elif available > 1:
                lines.extend(item_lines[:available - 1])
                lines.append(f"  [dim]... 共{len(p.inventory)}件[/]")
            else:
                lines.extend(item_lines[:max(1, available)])
        else:
            lines.append("  (空)")
        lines.append("")
        lines.append("[dim]:I序号 装备/使用  :U1-U6 卸除  :W 互换左右手[/]")
        lines.append("[dim][[I]]关闭 [[C]]角色面板 [[X]]观察[/]")
        return "\n".join(lines)

    def _render_character(self) -> str:
        p = self.state.player
        max_h = self.size.height
        exp_bar = "+" * int(p.class_exp * 10) + "_" * (10 - int(p.class_exp * 10))
        lines = [
            f"[bold]角色面板[/] [dim]C/Esc返回[/]  {p.name}  {p.faction}  {p.char_class} Lv.{p.class_level:.1f}",
            f"经验: [{exp_bar}]  {p.class_exp * 100:.0f}%",
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
        lines.append("── 装备 ──")
        lines.extend(self._render_equipment_lines(p))
        if p.statuses:
            lines.append(f"[red]状态: {' '.join(s.name for s in p.statuses)}[/]")
        lines.append("[dim][[C]]关闭 [[I]]物品栏 [[X]]观察[/]")
        return "\n".join(lines[:max_h])

    def _render_system(self) -> str:
        """渲染「- 思绪 -」面板。"""
        max_h = self.size.height
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
        return "\n".join(lines[:max_h])

    def _render_spellbook(self) -> str:
        """渲染法术书 —— 只记载已知法术本体。"""
        from core.spell import get_known_spells
        p = self.state.player
        known = get_known_spells(p)
        max_h = self.size.height
        lines = [f"[bold]法术书[/] [dim]B返回[/]", ""]
        if not known:
            lines.append("  (尚未记载任何法术)")
        for i, s in enumerate(known, 1):
            domain = s.get("domain_cn", s.get("domain", ""))
            lv = s.get("level", 0)
            mp = s.get("mp_cost", 0)
            lines.append(f"  [{i}] {s['name']}  {domain} Lv.{lv}  MP:{mp}")
        lines.append("")
        lines.append("[dim]:I序号 记忆/取消记忆  B返回[/]")
        return "\n".join(lines[:max_h])

    def _render_observe(self) -> str:
        cursor = self.state.observe_cursor
        cx, cy = cursor
        max_h = self.size.height
        lines = ["[bold]观察模式[/] [dim]X退出 方向键移动光标[/]", ""]

        # 地名 — 从 location_map 哈希表 O(1) 查询，不存在时回退到当前地图名
        loc = self.state.location_map.get(cursor, "")
        if not loc:
            loc = self.state.current_map or ""
        if loc:
            lines.append(f"位置: ({cx}, {cy}) {loc}")
        else:
            lines.append(f"位置: ({cx}, {cy})")

        # 特征（地下城入口/出口）
        t_here = self.state.map[cx, cy]
        if t_here == Terrain.STAIRS_DOWN:
            lines.append("特征: 洞口")
        elif t_here == Terrain.STAIRS_UP:
            lines.append("特征: 洞口（出口）")

        # 箱子
        if (cx, cy) in self.state.chests:
            chest_data = self.state.chests[(cx, cy)]
            gp = chest_data.get("gp", 0)
            gp_str = f" ({gp} GP)" if gp > 0 else ""
            lines.append(f"箱子: {chest_data.get('label', '箱子')}{gp_str}")

        # 地形
        terrain = self.state.map[cx, cy]
        t_names = {Terrain.GRASS: "草地", Terrain.BARREN: "荒地", Terrain.PLAIN: "平原", Terrain.FLOOR: "地面", Terrain.BED: "床铺", Terrain.STAIRS_DOWN: "楼梯下", Terrain.STAIRS_UP: "楼梯上", Terrain.WATER: "水", Terrain.BUSH: "灌木丛", Terrain.STONE: "石头", Terrain.LOW_WALL: "矮墙", Terrain.TREE: "树", Terrain.CAMPFIRE: "篝火", Terrain.DOOR: "门", Terrain.WALL: "墙壁"}
        lines.append(f"地表: {t_names.get(terrain, '未知')}")

        # 生物
        ent = self.state.get_entity_at(cx, cy)
        if ent:
            if ent is self.state.player:
                # 玩家自身：显示基础信息与状态（进水后的潮湿等），不显示态度/隐匿
                lines.append(f"生物: {ent.name}(你) Lv.{ent.class_level:.1f}  阵营:{ent.faction}")
                lines.append(f"  朝向: {facing_label(ent.facing)}  HP {ent.hp}/{ent.max_hp}")
                if ent.food_value > 0:
                    lines.append(f"  饮食: {ent.food_value * 100 // 15000}%")
                if ent.statuses:
                    lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")
            else:
                hp_pct = ent.hp / max(ent.max_hp, 1) * 100
                attitude = get_attitude(ent, self.state.player)
                att_color = {"敌对": "[red]敌对[/]", "友好": "[green]友好[/]", "冷漠": "[yellow]冷漠[/]"}.get(attitude, attitude)
                lines.append(f"生物: {ent.name} Lv.{ent.class_level:.1f}  阵营:{ent.faction}  态度:{att_color}")
                lines.append(f"  朝向: {facing_label(ent.facing)}  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)")
                if ent.food_value > 0:
                    lines.append(f"  饮食: {ent.food_value * 100 // 15000}%")
                if ent.statuses:
                    lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")
                if self.state._is_hidden_to(self.state.player, ent, (cx, cy)):
                    lines.append("  目标对你是隐匿的")

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
        player_pos = self.state.get_entity_pos(self.state.player)
        if player_pos is not None and self.state._cover_level((cx, cy), player_pos) == "light":
            lines.append("可见度: 轻度遮蔽")

        # 光照
        if cursor in self.state.fov_bright:
            lines.append("亮度: 明亮")
        elif cursor in self.state.fov_dim:
            lines.append("亮度: 微光")
        else:
            lines.append("亮度: 不可见")

        # 物品清单
        from core.item_actions import get_ground_items_at
        ground_at = get_ground_items_at(self.state.ground_items, cx, cy)
        if ground_at:
            lines.append("── 地上物品 ──")
            for g in ground_at:
                lines.append(f"  {g['name']} x{g['count']}")

        return "\n".join(lines[:max_h])

    @staticmethod
    def _render_equipment_lines(player) -> list[str]:
        """构建装备显示行列表（物品栏和角色面板共用）。"""
        slot_groups = [
            [("head", "头部"), ("chest", "躯干"), ("arms", "双臂"), ("legs", "双腿")],
            [("left_hand", "左手"), ("right_hand", "右手")],
            [("accessory1", "饰品1"), ("accessory2", "饰品2"), ("accessory3", "饰品3")],
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
        return lines
