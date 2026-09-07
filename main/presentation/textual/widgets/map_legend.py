"""地图图例 Widget —— 固定 3 行，显示 FOV 内字符含义，与 MapView 分离避免宽度变化导致布局抖动。"""
import re

from textual.widgets import Static

from domain.movement import Terrain
from domain.item_actions import ground_item_render
from presentation.textual.view_models import GameViewModel
from presentation.textual.widgets.map_view import FACTION_COLORS, TERRAIN_COLORS

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

_MARKUP = re.compile(r"\[/?[^\]]+\]")


def _visible_len(text: str) -> int:
    return len(_MARKUP.sub("", text))


def _entry(ch: str, name: str, color: str = "") -> str:
    if color:
        return f"[{color}]{ch}[/]{name}"
    return f"{ch}{name}"


def _item_render(item) -> dict | None:
    if getattr(item, "render_char", ""):
        return {"char": item.render_char, "color": item.render_color or "white"}
    return ground_item_render(item)


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

        by_char: dict[str, str] = {"@": _entry("@", "玩家", "green")}
        for creature, position in self.state.entities:
            if self.state.is_in_fov(position) and not creature.is_dead:
                color = FACTION_COLORS.get(creature.faction, "")
                by_char[creature.char] = _entry(creature.char, creature.name, color)

        for pos in fov:
            t = self.state.surface_at(pos[:2], pos[2]).terrain
            ch = TERRAIN_CHARS.get(t)
            label = TERRAIN_LABELS.get(t)
            if ch and label:
                by_char.setdefault(ch, _entry(ch, label, TERRAIN_COLORS.get(t, "")))

        item_entries: list[str] = []
        seen_items: set[tuple[str, str]] = set()
        for item, position in self.state.ground_items:
            if not self.state.is_in_fov(position):
                continue
            render_info = _item_render(item)
            if not render_info:
                continue
            ch = render_info["char"]
            key = (ch, item.name)
            if key in seen_items:
                continue
            seen_items.add(key)
            item_entries.append(_entry(ch, item.name, render_info.get("color", "")))

        entries = [by_char["@"]] + [
            text for ch, text in by_char.items() if ch != "@"
        ] + item_entries

        MAX_COLS = 40
        lines = []
        cur = ""
        for entry in entries:
            sep = " " if cur else ""
            if _visible_len(cur) + _visible_len(sep) + _visible_len(entry) <= MAX_COLS:
                cur += sep + entry
            else:
                lines.append(cur)
                cur = entry
                if len(lines) == 2:
                    shown = sum(len(_MARKUP.sub("", line).split()) for line in lines)
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
