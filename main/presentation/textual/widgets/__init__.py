"""Textual UI 组件。"""

from presentation.textual.widgets.top_bar import TopBar, PENDULUMS_PER_DAY, PENDULUMS_PER_MONTH, PENDULUMS_PER_YEAR
from presentation.textual.widgets.left_panel import LeftPanel
from presentation.textual.widgets.map_view import MapView, TERRAIN_COLORS, FACTION_COLORS
from presentation.textual.widgets.map_legend import MapLegend
from presentation.textual.widgets.right_panel import RightPanel
from presentation.textual.widgets.log_widgets import ActionLog, SceneLog

__all__ = [
    "TopBar", "PENDULUMS_PER_DAY", "PENDULUMS_PER_MONTH", "PENDULUMS_PER_YEAR",
    "LeftPanel",
    "MapView", "TERRAIN_COLORS", "FACTION_COLORS",
    "MapLegend",
    "RightPanel",
    "ActionLog", "SceneLog",
]
