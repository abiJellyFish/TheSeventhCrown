"""角色选择画面 —— 唤醒后选择战士或魔法使，魔法使需选领域，确认后进入游戏。"""
import json
import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static

from core.entity import create_fighter, create_mage

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")

# 角色元数据：name / key / class_label / file / factory
CHARACTERS = [
    {
        "name": "凯恩",
        "key": "fighter",
        "class_label": "战士",
        "file": "player_start.json",
        "factory": create_fighter,
    },
    {
        "name": "伊芙琳",
        "key": "mage",
        "class_label": "魔法使",
        "file": "player_start_mage.json",
        "factory": create_mage,
    },
]

# 魔法领域选项（MVP2.md：塑能 / 防护）
DOMAINS = [
    {"key": "evocation", "label": "塑能", "desc": "记忆魔法飞弹（1环塑能法术）"},
    {"key": "abjuration", "label": "防护", "desc": "记忆护盾术、疗伤术（1环防护法术）"},
]

# 职业展示信息（由 JSON / 工厂实时计算，避免硬编码）
_CLASS_INFO = {
    "fighter": {"hp": 35, "mp": None, "bonus": "力量+2 体质+2"},
    "mage":    {"hp": 30, "mp": 100, "bonus": "智力+2"},
}


def _load_start_data(file: str) -> dict:
    """从 data/ 加载角色初始 JSON。"""
    path = os.path.join(_DATA_DIR, file)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_desc(char: dict) -> str:
    """根据 JSON + 职业信息实时构建属性描述。"""
    info = _CLASS_INFO[char["key"]]
    parts = [f"{char['class_label']} | HP {info['hp']}"]
    if info["mp"] is not None:
        parts.append(f"MP {info['mp']}")
    parts.append(info["bonus"])
    return " | ".join(parts)


class CharSelectScreen(Screen):
    """角色选择画面 —— 上下键选择，Enter 确认，Esc 返回标题。"""

    CSS = """
    CharSelectScreen { align: center middle; }
    #char-choices { text-align: center; }
    """

    BINDINGS = [
        Binding("up", "move_up", "", priority=True),
        Binding("down", "move_down", "", priority=True),
        Binding("enter", "select", "", priority=True),
        Binding("escape", "back", "", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected = 0
        self._phase = "char_select"  # "char_select" | "domain_select"

    def compose(self) -> ComposeResult:
        yield Static(self._build_text(), id="char-choices")

    def _build_text(self) -> str:
        if self._phase == "domain_select":
            return self._build_domain_text()
        lines = ["[bold]── 请选择你的角色 ──[/]", ""]
        for i, char in enumerate(CHARACTERS):
            marker = ">" if i == self._selected else " "
            if i == self._selected:
                lines.append(f"[reverse]{marker} {char['name']} — {char['class_label']}[/]")
            else:
                lines.append(f"{marker} {char['name']} — {char['class_label']}")
            lines.append(f"  [dim]{_build_desc(char)}[/]")
            lines.append("")
        lines.append("[dim]上下键选择  Enter确认  Esc返回[/]")
        return "\n".join(lines)

    def _build_domain_text(self) -> str:
        lines = ["[bold]── 选择魔法领域 ──[/]", ""]
        for i, d in enumerate(DOMAINS):
            marker = ">" if i == self._selected else " "
            if i == self._selected:
                lines.append(f"[reverse]{marker} {d['label']}[/]")
            else:
                lines.append(f"{marker} {d['label']}")
            lines.append(f"  [dim]{d['desc']}[/]")
            lines.append("")
        lines.append("[dim]上下键选择  Enter确认  Esc返回[/]")
        return "\n".join(lines)

    def _characters_list(self) -> list[dict]:
        return CHARACTERS

    def action_move_up(self) -> None:
        count = len(DOMAINS) if self._phase == "domain_select" else len(CHARACTERS)
        self._selected = (self._selected - 1) % count
        self.query_one("#char-choices", Static).update(self._build_text())

    def action_move_down(self) -> None:
        count = len(DOMAINS) if self._phase == "domain_select" else len(CHARACTERS)
        self._selected = (self._selected + 1) % count
        self.query_one("#char-choices", Static).update(self._build_text())

    def action_select(self) -> None:
        if self._phase == "domain_select":
            domain = DOMAINS[self._selected]
            self.app.start_game_with("mage", domain=domain["key"])
            return
        char = CHARACTERS[self._selected]
        if char["key"] == "mage":
            self._phase = "domain_select"
            self._selected = 0
            self.query_one("#char-choices", Static).update(self._build_text())
            return
        self.app.start_game_with(char["key"])

    def action_back(self) -> None:
        if self._phase == "domain_select":
            self._phase = "char_select"
            self._selected = 0
            self.query_one("#char-choices", Static).update(self._build_text())
            return
        self.app.back_to_title()