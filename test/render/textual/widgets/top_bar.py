"""顶栏 —— 地图名、地名、天气、战斗轮次、时间信息。"""

from rich.text import Text
from textual.widgets import Static

from core.game_state import GameState

PENDULUMS_PER_DAY = 5000
PENDULUMS_PER_MONTH = 50000     # 10 天
PENDULUMS_PER_YEAR = 250000     # 5 月


class TopBar(Static):
    state: GameState | None = None

    @staticmethod
    def _get_location(s) -> str:
        """O(1) 哈希表查询，无分支。"""
        if s.in_dungeon:
            return "地下城1层"
        return s.location_map.get(s.player_pos, "平原")

    def render(self) -> str:
        if self.state is None:
            return ""
        s = self.state
        width = self.size.width
        pc = s.clock.pendulum_count
        day = (pc // PENDULUMS_PER_DAY) % 10 + 1
        month = (pc // PENDULUMS_PER_MONTH) % 5 + 1
        year = pc // PENDULUMS_PER_YEAR + 1
        current_pc = pc % PENDULUMS_PER_DAY  # 每天 5000 钟摆后清零

        map_name = s.current_map or "???"
        location = self._get_location(s)
        left = f" [bold]{map_name}[/] {location}  晴"

        right = f"{current_pc}钟摆 第{day}天 {month}月 {year}纪年 "

        def visible_len(t: str) -> int:
            return Text.from_markup(t).cell_len

        if s.in_combat and s.combat_initiative:
            # 存活参战者，当前回合生物前后各 2 个，超出用 +N 省略
            alive = [e for e in s.combat_initiative if not e.is_dead or e is s.player]
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
