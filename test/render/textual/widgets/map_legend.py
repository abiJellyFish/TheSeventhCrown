"""地图图例 Widget —— 固定 3 行，显示 FOV 内字符含义，与 MapView 分离避免宽度变化导致布局抖动。"""

from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain


class MapLegend(Static):
    """地图图例，固定 3 行高度，超出的条目合并为 +N。"""

    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return "\n\n"
        fov = self.state.fov_cache
        gmap = self.state.map

        legend_seen: dict[str, str] = {"@": "玩家"}
        for creature, (ec, er) in self.state.entities:
            if (ec, er) in fov and creature.hp > 0:
                legend_seen[creature.char] = creature.name

        terrain_map = {Terrain.WALL: "#", Terrain.DIFFICULT: '"', Terrain.PASSABLE: "."}
        terrain_labels = {"#": "墙壁", '"': "灌木", ".": "草地"}
        for pos in fov:
            t = gmap[pos]
            ch = terrain_map.get(t)
            if ch:
                legend_seen.setdefault(ch, terrain_labels[ch])
            if pos in self.state.bed_positions:
                legend_seen["="] = "床"
            if pos in self.state.stone_positions:
                legend_seen["o"] = "石头"
            if pos in self.state.campfire_positions:
                legend_seen["~"] = "篝火"
            if pos in self.state.door_states:
                legend_seen["]"] = "门"
            if self.state.dungeon_entrance and pos == self.state.dungeon_entrance:
                legend_seen[">"] = "入口"

        entries = [f"@玩家"] + [f"{ch}{name}" for ch, name in legend_seen.items() if ch != "@"]

        # 排版：每行填满，最多 3 行，超出合并
        MAX_COLS = 40
        lines = []
        cur = ""
        for entry in entries:
            sep = " " if cur else ""
            if len(cur) + len(sep) + len(entry) <= MAX_COLS:
                cur += sep + entry
            else:
                lines.append(cur)
                cur = entry
                if len(lines) == 2:
                    # 第 3 行：剩余全部塞入，截断
                    rest = [entry] + [e for e in entries if e not in [x for line in lines for x in line.split()] and e != entry]
                    # 去重简化：直接用计数
                    shown = sum(len(line.split()) for line in lines)
                    remaining = len(entries) - shown
                    if remaining > 0:
                        overflow = entries[shown:]
                        if len(overflow) <= 3:
                            lines.append(" ".join(overflow))
                        else:
                            lines.append(" ".join(overflow[:2]) + f" +{len(overflow) - 2}")
                    break
        if cur and len(lines) < 3:
            lines.append(cur)

        while len(lines) < 3:
            lines.append("")
        return "\n".join(lines[:3])
