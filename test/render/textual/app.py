"""Textual MVP App —— 最小可运行游戏原型。

启动: python -m render.textual.app
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual import events

from core.game_state import GameState
from core.entity import Player, Creature
from core.movement import Terrain
from core.grid import Grid
from core.fov import LightLevel, compute_fov


# ── Map display widget ──

class MapView(Static):
    """ASCII 地图渲染组件。"""

    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return "Loading..."

        gmap = self.state.map
        player_col, player_row = self.state.player_pos

        # 计算可见区域 (视口跟随玩家, 默认 20x15)
        vw, vh = 40, 20
        ox = max(0, min(player_col - vw // 2, gmap.width - vw))
        oy = max(0, min(player_row - vh // 2, gmap.height - vh))

        lines = []
        for row in range(oy, min(oy + vh, gmap.height)):
            line_chars = []
            for col in range(ox, min(ox + vw, gmap.width)):
                # 实体优先
                entity = self.state.get_entity_at(col, row)
                if entity is not None:
                    ch = entity.name[0] if entity.name else "?"
                    if entity.faction == "hostile":
                        line_chars.append(f"[red]{ch}[/]")
                    elif entity.faction == "friendly":
                        line_chars.append(f"[green]{ch}[/]")
                    else:
                        line_chars.append(f"[yellow]{ch}[/]")
                elif (col, row) == (player_col, player_row):
                    line_chars.append("[bold bright_cyan]@[/]")
                else:
                    t = gmap[col, row]
                    if t == Terrain.WALL:
                        line_chars.append("[grey]#[/]")
                    elif t == Terrain.DIFFICULT:
                        line_chars.append("[dim]\"[/]")
                    else:
                        line_chars.append(". ")
            lines.append("".join(line_chars))
        return "\n".join(lines)


# ── Status panel ──

class StatusPanel(Static):
    """角色状态面板。"""

    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return ""
        p = self.state.player
        col, row = self.state.player_pos
        lines = [
            f"[bold]{p.name}[/]  [dim]Lv.1 {p.char_class}[/]",
            f"HP: [green]{p.hp}/{p.max_hp}[/]",
            f"MP: [blue]{p.mp}/{p.max_mp}[/]",
            f"韧: [yellow]{p.tenacity}/{p.max_tenacity}[/]",
            f"AC: {p.total_ac('chest')}",
            f"Pos: ({col}, {row})",
            f"AP: {p.ap}/{p.max_ap}",
            "",
            "[dim]WASD/方向键 移动[/]",
            "[dim]Q 退出[/]",
        ]
        if p.statuses:
            lines.append(f"[red]状态: {', '.join(p.statuses)}[/]")
        return "\n".join(lines)


# ── Log panel ──

class LogPanel(Static):
    """日志面板。"""

    messages: list[str] = []

    def add(self, msg: str) -> None:
        self.messages.append(msg)
        if len(self.messages) > 100:
            self.messages = self.messages[-50:]
        self.refresh()

    def render(self) -> str:
        recent = self.messages[-8:] if self.messages else ["欢迎来到 MVP 原型"]
        return "\n".join(f"[dim]{m}[/]" for m in recent)


# ── App ──

class MVPApp(App):
    """MVP 游戏主应用。"""

    CSS = """
    Horizontal { height: 100%; }
    Vertical { height: 100%; }
    MapView {
        width: 60%;
        height: 100%;
        border: solid grey;
        content-align: left top;
    }
    #right-panel {
        width: 40%;
        height: 100%;
    }
    StatusPanel {
        height: 30%;
        border: solid grey;
    }
    LogPanel {
        height: 70%;
        border: solid grey;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("up,w", "move_up", "Up"),
        ("down,s", "move_down", "Down"),
        ("left,a", "move_left", "Left"),
        ("right,d", "move_right", "Right"),
    ]

    def __init__(self):
        super().__init__()
        self._state = self._create_game_state()
        self._log_panel: LogPanel | None = None

    def _create_game_state(self) -> GameState:
        player = Player.create_fighter(name="凯恩",
                                       stats={"str": 8, "dex": 8, "con": 8,
                                              "int": 8, "wis": 8, "cha": 8})
        state = GameState(player=player, map_width=50, map_height=30)
        state.player_pos = (5, 5)

        # 放一些墙和 NPC
        for i in range(10, 20):
            state.map[i, 10] = Terrain.WALL
        for i in range(5, 15):
            state.map[15, i] = Terrain.WALL
        # 一个测试 NPC
        goblin = Creature(name="goblin", faction="hostile",
                          hp=20, max_hp=20)
        state.add_entity(goblin, (12, 8))
        elder = Creature(name="elder", faction="friendly",
                         hp=22, max_hp=22)
        state.add_entity(elder, (6, 6))

        return state

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            self._map_view = MapView()
            self._map_view.state = self._state
            yield self._map_view
            with Vertical(id="right-panel"):
                self._status_panel = StatusPanel()
                self._status_panel.state = self._state
                yield self._status_panel
                self._log_panel = LogPanel()
                yield self._log_panel
        yield Footer()

    def on_mount(self) -> None:
        self._log_panel.add("按方向键移动 @ 探索地图")
        self._log_panel.add("红色字符 = 敌对生物, 绿色 = 友好")

    def _move(self, dc: int, dr: int) -> None:
        col, row = self._state.player_pos
        new_col, new_row = col + dc, row + dr
        result = self._state.move_player(new_col, new_row)
        if result:
            # 检查是否有实体在目标格
            entity = self._state.get_entity_at(new_col, new_row)
            if entity:
                self._log_panel.add(f"前方有 {entity.name} (faction: {entity.faction})")
            self._map_view.refresh()
            self._status_panel.refresh()

    def action_move_up(self): self._move(0, -1)
    def action_move_down(self): self._move(0, 1)
    def action_move_left(self): self._move(-1, 0)
    def action_move_right(self): self._move(1, 0)


if __name__ == "__main__":
    app = MVPApp()
    app.run()
