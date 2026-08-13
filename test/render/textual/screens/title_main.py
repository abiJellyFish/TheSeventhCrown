"""title_test + crown_test 合并：crown 右移10下移10，title 优先覆盖 crown，不穿插。"""
import unicodedata

from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.screen import Screen
from textual.binding import Binding


_ROW1_RAW = """\
    .....
 .H8888888h.  ~-.    .uef^"
 888888888888x  `> :d88E
X~     `?888888hx~ `888E            .u
'      x8.^"*88*"   888E .z8k    ud8888.
 `-:- X8888x        888E~?888L :888'8888.
      488888>       888E  888E d888 '88%"
    .. `"88*        888E  888E 8888.+"
  x88888nX"      .  888E  888E 8888L
 !"*8888888n..  :   888E  888E '8888c. .+
'    "*88888888*   m888N= 888>  "88888%
        ^"***"`     `Y"   888     "YP'
                         J88"
                         @%
                       :"
"""

_ROW2_RAW = """\
       ...
   .x888888hx    :              u                                       :8      .uef^"
  d88888888888hxx              88Nu.   u.                u.    u.      .88    :d88E
 8" ... `"*8888%`       .u    '88888.o888c      .u     x@88k u@88c.   :888ooo `888E
!  "   ` .xnxx.      ud8888.   ^8888  8888   ud8888.  ^"8888""8888" -*8888888  888E .z8k
X X   .H8888888%:  :888'8888.   8888  8888 :888'8888.   8888  888R    8888     888E~?888L
X 'hn8888888*"   > d888 '88%"   8888  8888 d888 '88%"   8888  888R    8888     888E  888E
X: `*88888%`     ! 8888.+"      8888  8888 8888.+"      8888  888R    8888     888E  888E
'8h.. ``     ..x8> 8888L       .8888b.888P 8888L        8888  888R   .8888Lu=  888E  888E
 `88888888888888f  '8888c. .+   ^Y8888*""  '8888c. .+  "*88*" 8888"  ^%888*    888E  888E
  '%8888888888*"    "88888%       `Y"       "88888%      ""   'Y"      'Y"    m888N= 888>
     ^"****""`        "YP'                    "YP'                             `Y"   888
                                                                                    J88"
                                                                                    @%
                                                                                  :"
"""

ROW3_LINES = [
    "      ...",
    "   xH88\"`~ .x8X                               x=~",
    " :8888   .f\"8888Hf    .u    .          u.    88x.   .e.   .e.     u.    u.",
    ":8888>  X8L  ^\"\"`   .d88B :@8c   ...ue888b  '8888X.x888:.x888   x@88k u@88c.",
    "X8888  X888h       =\"8888f8888r  888R Y888r  `8888  888X '888k ^\"8888\"\"8888\"",
    "88888  !88888.       4888>'88\"   888R I888>   X888  888X  888X   8888  888R",
    "88888   %88888       4888> '     888R I888>   X888  888X  888X   8888  888R",
    "88888 '> `8888>      4888>       888R I888>   X888  888X  888X   8888  888R",
    "`8888L %  ?888   !  .d888L .+   u8888cJ888   .X888  888X. 888~   8888  888R",
    " `8888  `-*\"\"   /   ^\"8888*\"     \"*888*P\"    `%88%``\"*888Y\"     \"*88*\" 8888\"",
    "   \"888.      :\"       \"Y\"         'Y\"         `~     `\"          \"\"   'Y\"",
    "     `\"\"***~`",
]

_CROWN_RAW = """
                                                                                     -
                                                                                   .%.
                                                                                 .=+%
                                                                               .=++*+
                                                                             .=++++%.
                                        :%.                                .=++++ +%.
                                          *%++==-.                       .=++++   *#
                                            %#+++++++++-.               =++++    +*#
                                             :@++++++++++++++=:.     .+++++      +#-
                                               *%+++   +++++++++++++++++++       +%
                                                .%*+++        +++++++++          +#
                                                  =%+++                          #=
                                                    *#+++                        %=
                                                     :%*+++                      -:
                                                       =%+++                     ++=:
                                                         ##++                    ++++=:
                                                          :%*                      ++++=:
                                                           .-                        ++++=:
                                                           :+                          ++++-:
                                                          :=+                            ++++=:
                                                         .=++         +++++++++++          ++++=:
                                                        .-++        +++*@+@@@#+++++++++      ++++-:
                                                        :++        +++@*       -%@@%++++++++++ ++++=:
                                                       :=+       +++*%               .*%@@*++++++++++=:
                                                      .=++      +++@+                       -#%@#*+++++-:
                                                     .-++     +++#%                               .*#@%**-:
                                                     :++     +++@-                                       =*#=
                                                    :=+    +++##
                                                   .=++   +++@-
                                                  .-++  +++##
                                                  :++  ++*@:
                                                 :=+ +++#*
                                                :=++++*@:
                                               .-++++%*
                                               :+++*@.
                                              :=++%*
                                             .=+*@.
                                            .-+%*
                                            :*%.
                                           :%+
                                          :#
                                         :=
"""

_CROWN_BASE_OFFSET = 85
_CROWN_HOFFSET = _CROWN_BASE_OFFSET + 10   # crown 整体右移 10 格
_CROWN_VOFFSET = 5                         # crown 下移 5 格（相对下移10 上移5格）


def _strip_common(text):
    """去掉整段最小公共前导空格，保留内部相对位置。"""
    lines = text.strip("\n").split("\n")
    n = min((len(l) - len(l.lstrip(" ")) for l in lines if l.strip()), default=0)
    return [l[n:] for l in lines]


def _dwidth(s):
    """按终端显示宽度计算字符串宽度：CJK 等全角字符算 2，ASCII 算 1。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


# 菜单配色与布局
_MENU_TEXT = "white"          # 选项文字（白）
_MENU_BORDER_DIM = "#5f5f5f"  # 未选中边框（暗灰）
_MENU_BLUE = "#87CEEB"        # 选中 唤醒/回忆 边框（浅蓝）
_MENU_PURPLE = "#DDA0DD"      # 选中 入眠 边框（浅紫）
_MENU_BG = "#1c1c1c"          # 文字周围一圈终端背景色（环）
_MENU_RING = 1                # 文字左右各 1 格背景环
_MENU_GAP = 5                 # 边框到文字环的空格间距（矩形加宽）
_MENU_HALO = 1                # 选项框外围一圈空格（隔离背景）
_MENU_BOTTOM_MARGIN = 3       # 菜单距窗口底部留白（整体上移）

_VERSION_TEXT = "TheSeventhCrown v0.1"
_VERSION_COLOR = "#808080"    # 版本号颜色（暗灰）
_VERSION_HALO = 1             # 版本号周围一圈空格


row1 = _strip_common(_ROW1_RAW)
row2 = _strip_common(_ROW2_RAW)
row3 = _strip_common("\n".join(ROW3_LINES))
crown = _strip_common(_CROWN_RAW)


class MergedArt(Static):
    """标题 + 皇冠 + 底部三字菜单，单图层渲染（避免图层遮挡背景整行）。"""

    LABELS = ("唤醒", "回忆", "入眠")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.selected = 0

    def move_up(self) -> None:
        self.selected = (self.selected - 1) % len(self.LABELS)

    def move_down(self) -> None:
        self.selected = (self.selected + 1) % len(self.LABELS)

    def current_label(self) -> str:
        return self.LABELS[self.selected]

    def _build_art_grid(self, W: int) -> list:
        """构建背景网格（标题 + 皇冠），返回 list[list[str]]，高 art_h、宽 W。"""
        w1 = max(len(l) for l in row1)
        w2 = max(len(l) for l in row2)
        w3 = max(len(l) for l in row3)
        off1 = (W - w1) // 2
        off2 = (W - w2) // 2
        off3 = W - (w3 + 20)

        total_h = max(len(row1) + len(row2) + len(row3),
                      _CROWN_VOFFSET + len(crown))
        grid = [[" "] * W for _ in range(total_h)]
        occupied = set()

        def paint(row_lines, offset, start_y):
            for i, line in enumerate(row_lines):
                y = start_y + i
                if y >= total_h:
                    break
                for j, ch in enumerate(line):
                    if ch != " ":
                        x = offset + j
                        if 0 <= x < W:
                            grid[y][x] = ch
                            for dy in (-1, 0, 1):
                                for dx in (-1, 0, 1):
                                    occupied.add((y + dy, x + dx))

        paint(row1, off1, 0)
        paint(row2, off2, len(row1))
        paint(row3, off3, len(row1) + len(row2))

        for i, line in enumerate(crown):
            y = _CROWN_VOFFSET + i
            if y >= total_h:
                break
            for j, ch in enumerate(line):
                if ch != " ":
                    x = _CROWN_HOFFSET + j
                    if 0 <= x < W and (y, x) not in occupied:
                        grid[y][x] = ch

        return grid

    def _menu_segment(self, label, box_index, row, inner):
        """返回某菜单框某一行的带 markup 字符串（可见宽 = inner + 2）。"""
        selected = (box_index == self.selected)
        if selected:
            frame = _MENU_PURPLE if label == "入眠" else _MENU_BLUE
        else:
            frame = _MENU_BORDER_DIM

        if row in (0, 2):
            return f"[{frame}]+{'-' * inner}+[/]"

        # 内容行：框内间距与文字环均为空格，不渲染背景字符
        text_w = _dwidth(label)
        gap = " " * _MENU_GAP
        ring = " " * _MENU_RING

        if selected:
            pad_l = " " * ((inner - text_w) // 2)
            pad_r = " " * (inner - text_w - len(pad_l))
            return (
                f"[{frame}]|[/]"
                f"[on {frame}]{pad_l}[/]"
                f"[{_MENU_BG} on {frame}]{label}[/]"
                f"[on {frame}]{pad_r}[/]"
                f"[{frame}]|[/]"
            )

        return (
            f"[{frame}]|[/]"
            f"{gap}"
            f"[on {_MENU_BG}]{ring}[/]"
            f"[{_MENU_TEXT} on {_MENU_BG}]{label}[/]"
            f"[on {_MENU_BG}]{ring}[/]"
            f"{gap}"
            f"[{frame}]|[/]"
        )

    def render(self) -> str:
        W = self.size.width
        H = self.size.height
        if W <= 0:
            return ""
        if H <= 0:
            H = 1

        art_grid = self._build_art_grid(W)
        art_h = len(art_grid)

        # 画布高 = 窗口高；背景只取前 H 行
        frame = [[" "] * W for _ in range(H)]
        for y in range(min(art_h, H)):
            frame[y] = art_grid[y]

        # 菜单几何：三框竖排，整体贴近窗口底部
        text_w = max(_dwidth(l) for l in self.LABELS)
        inner = text_w + 2 * _MENU_RING + 2 * _MENU_GAP
        box_w = inner + 2
        box_x = max(0, (W - box_w) // 2)
        menu_h = len(self.LABELS) * 3
        menu_top = H - menu_h - _MENU_BOTTOM_MARGIN

        # 清空菜单区（框 + 周围一圈）为空格，避免背景字符透出
        for y in range(menu_top - _MENU_HALO, menu_top + menu_h + _MENU_HALO):
            for x in range(box_x - _MENU_HALO, box_x + box_w + _MENU_HALO):
                if 0 <= y < H and 0 <= x < W:
                    frame[y][x] = " "

        for mi, label in enumerate(self.LABELS):
            top = menu_top + mi * 3
            for r in range(3):
                y = top + r
                if 0 <= y < H:
                    seg = self._menu_segment(label, mi, r, inner)
                    base = "".join(frame[y])
                    frame[y] = list(base[:box_x] + seg + base[box_x + box_w:])

        # 版本号：右下角，周围一圈空格
        version_w = len(_VERSION_TEXT)
        vx = W - version_w - _VERSION_HALO
        vy = H - 1 - _VERSION_HALO
        for yy in range(vy - _VERSION_HALO, vy + 1 + _VERSION_HALO):
            for xx in range(vx - _VERSION_HALO, vx + version_w + _VERSION_HALO):
                if 0 <= yy < H and 0 <= xx < W:
                    frame[yy][xx] = " "
        base = "".join(frame[vy])
        frame[vy] = list(base[:vx] + f"[{_VERSION_COLOR}]{_VERSION_TEXT}[/]" + base[vx + version_w:])

        return "\n".join("".join(r).rstrip() for r in frame)


class TitleScreen(Screen):
    CSS = """
    TitleScreen {
        background: #1c1c1c;
    }
    #merged {
        color: gold;
        text-align: left;
        width: 100%;
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("up", "move_up", "", priority=True),
        Binding("down", "move_down", "", priority=True),
        Binding("enter", "select", "", priority=True),
    ]

    def compose(self) -> ComposeResult:
        self._merged = MergedArt(id="merged")
        yield self._merged

    def action_move_up(self) -> None:
        self._merged.move_up()
        self._merged.refresh()

    def action_move_down(self) -> None:
        self._merged.move_down()
        self._merged.refresh()

    def action_select(self) -> None:
        label = self._merged.current_label()
        if label == "唤醒":
            start = getattr(self.app, "start_new_game", None)
            if start:
                start()
        elif label == "回忆":
            self.app.notify("存档功能开发中")
        elif label == "入眠":
            self.app.exit()


class MergedApp(App):
    def on_mount(self) -> None:
        self.push_screen(TitleScreen())


if __name__ == "__main__":
    MergedApp().run()
