"""顶栏 —— 地图名、地名、高度、天气、日时段、战斗轮次、时间信息。"""

from rich.text import Text
from textual.widgets import Static

from domain.calendar import format_clock_right
from presentation.textual.view_models import GameViewModel


def location_name(state) -> str:
    """O(1) 哈希表查询；无受控坐标时用默认地名。"""
    pos = state.controlled_entity_pos
    if pos is None:
        return "平原"
    return state.location_map.get(pos[:2], "平原")


def left_text(state) -> str:
    map_name = state.current_map or "???"
    height = getattr(state.controlled_entity, "z", state.active_z)
    return f" [bold]{map_name}[/] {location_name(state)} 高度{height}"


def right_text(state) -> str:
    return f"晴 {format_clock_right(state.clock.pendulum_count)} "


class TopBar(Static):
    view_model: GameViewModel | None = None

    def set_view_model(self, view_model: GameViewModel, *, refresh: bool = True) -> None:
        self.view_model = view_model
        if refresh:
            self.refresh()

    @property
    def state(self):
        return self.view_model.snapshot if self.view_model is not None else None

    def render(self) -> str:
        if self.state is None:
            return ""
        s = self.state
        width = self.size.width
        left = left_text(s)
        right = right_text(s)

        def visible_len(t: str) -> int:
            return Text.from_markup(t).cell_len

        if s.in_combat and s.combat_initiative:
            # 存活参战者，当前回合生物前后各 2 个，超出用 +N 省略
            alive = [e for e in s.combat_initiative if not e.is_dead or e is s.controlled_entity]
            if not alive:
                pad = max(1, width - visible_len(left) - visible_len(right) - 2)
                return f"{left}{' ' * pad}{right}"
            current_idx = 0
            for i, e in enumerate(alive):
                if e is s.combat_turn_entity:
                    current_idx = i
                    break
            total = len(alive)
            if total <= 5:
                indices = list(range(total))
                prefix = ""
                suffix = ""
            else:
                start = max(0, current_idx - 2)
                end = min(total, current_idx + 3)
                indices = list(range(start, end))
                prefix = f"+{start} " if start > 0 else ""
                suffix = f" +{total - end}" if end < total else ""
            names = []
            for i in indices:
                e = alive[i]
                nm = e.name
                if e is s.combat_turn_entity:
                    nm = f"[bold yellow]{nm}[/]"
                names.append(nm)
            center = f"{prefix}{' > '.join(names)}{suffix}"
            # 确保右侧始终固定在屏幕右端，center 溢出时截断
            right_len = visible_len(right)
            left_len = visible_len(left)
            center_len = visible_len(center)
            if left_len + center_len + right_len > width:
                available = width - left_len - right_len
                if available < 4:
                    center = ""
                elif center_len > available:
                    # 用 Rich Text 安全截断，不破坏 markup 标签
                    t = Text.from_markup(center)
                    t.truncate(available, overflow="ellipsis")
                    center = t.markup
            center_len = visible_len(center)
            used = left_len + center_len + right_len
            remaining = max(0, width - used)
            pad_left = remaining // 2
            pad_right = remaining - pad_left
            return f"{left}{' ' * pad_left}{center}{' ' * pad_right}{right}"
        else:
            # 右侧始终完整显示，不截断
            pad = max(1, width - visible_len(left) - visible_len(right))
            return f"{left}{' ' * pad}{right}"
