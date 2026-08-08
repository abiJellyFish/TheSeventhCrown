"""右侧面板 —— 默认状态、物品栏、角色面板、观察模式子面板。"""

from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain


class RightPanel(Static):
    state: GameState | None = None
    view_mode: str = "default"  # "default" | "inventory" | "character"

    def render(self) -> str:
        if self.state is None:
            return ""
        if self.state.observe_mode:
            return self._render_observe()
        if self.view_mode == "inventory":
            return self._render_inventory()
        elif self.view_mode == "character":
            return self._render_character()
        return self._render_default()

    def _render_default(self) -> str:
        p = self.state.player
        slow_tag = " [dim]慢速[/]" if self.state.slow_mode else ""
        lines = [
            f"[bold]{p.name}[/]  人类 Lv.1 {p.char_class}{slow_tag}",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}",
            "",
            "[[X]]观察 [[Q]]退出",
            "[[C]]角色面板 [[I]]物品栏 [[B]]法术书",
            "[[Z]]制作 [[K]]烹饪 [[Y]]炼药",
            "[[H]]高度 [[M]]地图 [[E]]系统",
        ]
        if p.statuses:
            lines.append(f"[red]{' '.join(s.name for s in p.statuses)}[/]")
        return "\n".join(lines)

    def _render_inventory(self) -> str:
        p = self.state.player
        max_h = self.size.height
        lines = [
            f"[bold]物品栏[/] [dim]I/Esc返回  输入 :I序号 使用[/]",
            f"金币: {p.gp}GP",
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
            available = max_h - len(lines) - 1
            if available >= len(item_lines):
                lines.extend(item_lines)
            elif available > 1:
                lines.extend(item_lines[:available - 1])
                lines.append(f"  [dim]... 共{len(p.inventory)}件[/]")
            else:
                lines.extend(item_lines[:max(1, available)])
        else:
            lines.append("  (空)")
        return "\n".join(lines)

    def _render_character(self) -> str:
        p = self.state.player
        max_h = self.size.height
        lines = [
            f"[bold]角色面板[/] [dim]C/Esc返回[/]  {p.name}  {p.char_class} Lv.1",
            f"HP [green]{p.hp}/{p.max_hp}[/]  MP [blue]{p.mp}/{p.max_mp}[/]  TEN [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC 头部{p.total_ac('head')} 躯干{p.total_ac('chest')} 双臂{p.total_ac('arms')} 双腿{p.total_ac('legs')}",
            f"SPD {p.speed}  INIT +{p.initiative_bonus()}  金币: {p.gp}GP",
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
            lines.append(f"[red]状态: {' '.join(p.statuses)}[/]")
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

        # 地形
        terrain = self.state.map[cx, cy]
        t_names = {Terrain.WALL: "墙壁", Terrain.DIFFICULT: "灌木/困难地形", Terrain.PASSABLE: "草地/平地"}
        lines.append(f"地表: {t_names.get(terrain, '未知')}")

        # 生物
        ent = self.state.get_entity_at(cx, cy)
        if ent and ent is not self.state.player:
            hp_pct = ent.hp / max(ent.max_hp, 1) * 100
            faction_tag = {"hostile": "[red]敌对[/]", "friendly": "[green]友好[/]",
                           "neutral": "[yellow]中立[/]"}.get(ent.faction, ent.faction)
            lines.append(f"生物: {ent.name} {faction_tag}  HP {ent.hp}/{ent.max_hp} ({hp_pct:.0f}%)")
            if ent.statuses:
                lines.append(f"  状态: {', '.join(s.name for s in ent.statuses)}")

        # 光照
        if cursor in self.state.fov_cache:
            lines.append("亮度: 可见")
        else:
            lines.append("亮度: 不可见")

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
                parts.append(f"{label}:{item.name if item else '-'}")
            lines.append("  " + " ".join(parts))
        return lines
