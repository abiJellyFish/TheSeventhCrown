"""物品栏 — 全屏覆盖，显示装备槽和背包物品。"""

from textual.screen import Screen
from textual.widgets import Static
from textual.binding import Binding

from core.entity import Player


class InventoryScreen(Screen):
    BINDINGS = [
        Binding("escape", "close", "关闭", priority=True),
        Binding("i", "close", "关闭", priority=True),
        Binding("q", "close", "关闭", priority=True),
    ]

    CSS = """
    InventoryScreen {
        align: center middle;
    }
    #inv-panel {
        width: 55;
        height: auto;
        border: solid #444444;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, player: Player):
        super().__init__()
        self._player = player

    def compose(self):
        yield Static(self._render_panel(), id="inv-panel")

    def _render_panel(self) -> str:
        p = self._player
        lines = [
            f"[bold]物品栏[/]  金币: {p.gp}GP {p.sp}SP {p.cp}CP",
            "",
            "── 装备 ──",
        ]

        slot_names = {
            "head": "头部", "chest": "躯干", "arms": "双臂", "legs": "双腿",
            "left_hand": "左手", "right_hand": "右手",
            "accessory1": "饰品1", "accessory2": "饰品2", "accessory3": "饰品3",
        }
        for slot, label in slot_names.items():
            item = p.equipment.get(slot)
            item_text = item.name if item else "无"
            lines.append(f"  {label}: {item_text}")

        lines.append("")
        lines.append("── 背包 ──")

        if p.inventory:
            for i, item in enumerate(p.inventory):
                item_type = getattr(item, "item_type", "")
                type_tag = f"[dim]({item_type})[/]" if item_type else ""
                lines.append(f"  [{i+1}] {item.name} {type_tag}")
                if item.description:
                    lines.append(f"      {item.description[:40]}")
        else:
            lines.append("  (空)")

        return "\n".join(lines)

    def action_close(self):
        self.dismiss()
