"""地图图例 Widget —— 固定 3 行，显示 FOV 内字符含义，与 MapView 分离避免宽度变化导致布局抖动。"""

from textual.widgets import Static

from domain.movement import Terrain
from domain.item_actions import GROUND_ITEM_RENDER
from presentation.textual.view_models import GameViewModel

TERRAIN_CHARS = {
    Terrain.GRASS: ".", Terrain.BARREN: ".", Terrain.PLAIN: ".",
    Terrain.FLOOR: ".", Terrain.WATER: "^",
    Terrain.STAIRS_DOWN: ">", Terrain.STAIRS_UP: "<",
}
TERRAIN_LABELS = {
    Terrain.GRASS: "草地", Terrain.BARREN: "荒地", Terrain.PLAIN: "平原",
    Terrain.FLOOR: "地面", Terrain.WATER: "水",
    Terrain.STAIRS_DOWN: "入口", Terrain.STAIRS_UP: "出口",
}


class MapLegend(Static):
    """地图图例，固定 3 行高度，超出的条目合并为 +N。"""

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
            return "\n\n"
        fov = self.state.fov_cache
        gmap = self.state.map

        legend_seen: dict[str, str] = {"@": "玩家"}
        for creature, (ec, er) in self.state.entities:
            if (ec, er) in fov and not creature.is_dead:
                legend_seen[creature.char] = creature.name

        for pos in fov:
            t = gmap[pos]
            ch = TERRAIN_CHARS.get(t)
            label = TERRAIN_LABELS.get(t)
            if ch and label:
                legend_seen.setdefault(ch, label)
        for item, (ec, er) in self.state.ground_items:
            if (ec, er) in fov:
                render_info = (
                    {"char": item.render_char, "color": item.render_color}
                    if getattr(item, "render_char", "")
                    else GROUND_ITEM_RENDER.get(item.item_type)
                )
                if render_info:
                    legend_seen[render_info["char"]] = item.name

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
        result = "\n".join(lines[:3])
        return result
