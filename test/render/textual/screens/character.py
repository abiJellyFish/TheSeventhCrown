"""角色面板 — 全屏覆盖，显示角色完整属性。"""

from textual.screen import Screen
from textual.widgets import Static
from textual.binding import Binding

from core.entity import Player

STAT_NAMES = {"str": "力量", "dex": "敏捷", "con": "体质", "int": "智力", "wis": "感知", "cha": "魅力"}


class CharacterScreen(Screen):
    BINDINGS = [
        Binding("escape", "close", "关闭", priority=True),
        Binding("c", "close", "关闭", priority=True),
        Binding("q", "close", "关闭", priority=True),
    ]

    CSS = """
    CharacterScreen {
        align: center middle;
    }
    #char-panel {
        width: 50;
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
        yield Static(self._render_panel(), id="char-panel")

    def _render_panel(self) -> str:
        p = self._player
        lines = [
            f"[bold]{p.name}[/]  人类 {p.char_class}  Lv.1",
            "",
            f"HP  [green]{p.hp}/{p.max_hp}[/]    MP  [blue]{p.mp}/{p.max_mp}[/]    TEN  [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            "",
            f"AC  头部{p.total_ac('head')}  躯干{p.total_ac('chest')}  双臂{p.total_ac('arms')}  双腿{p.total_ac('legs')}",
            f"SPD {p.speed}    INIT +{p.initiative_bonus()}",
            "",
            "─" * 20,
            "",
        ]
        for key, label in STAT_NAMES.items():
            val = p.stat(key)
            adj = p.stat_adjust(key)
            sign = "+" if adj >= 0 else ""
            lines.append(f"  {label}: {val} ({sign}{adj})")

        lines.append("")
        lines.append("─" * 20)
        lines.append("")

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
        lines.append(f"金币: {p.gp}GP  {p.sp}SP  {p.cp}CP")

        if p.statuses:
            lines.append(f"[red]状态: {' '.join(p.statuses)}[/]")

        return "\n".join(lines)

    def action_close(self):
        self.dismiss()
