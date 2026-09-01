"""地图视图 —— 单字符 ASCII 渲染，FOV 裁剪，动态图例。"""

from rich.text import Text
from textual.widgets import Static

from domain.movement import Terrain
from domain.item_actions import GROUND_ITEM_RENDER, get_ground_items_at
from presentation.textual.view_models import GameViewModel

TERRAIN_COLORS = {
    Terrain.GRASS:        "rgb(140,210,120)",
    Terrain.BARREN:       "rgb(150,150,150)",
    Terrain.PLAIN:        "rgb(200,200,100)",
    Terrain.FLOOR:        "rgb(60,60,60)",
    Terrain.WATER:        "rgb(100,160,255)",
    Terrain.STAIRS_DOWN:  "magenta",
    Terrain.STAIRS_UP:    "magenta",
}
TERRAIN_CHARS = {
    Terrain.GRASS:        ".",
    Terrain.BARREN:       ".",
    Terrain.PLAIN:        ".",
    Terrain.FLOOR:        ".",
    Terrain.WATER:        "^",
    Terrain.STAIRS_DOWN:  ">",
    Terrain.STAIRS_UP:    "<",
}
FACTION_COLORS = {"守序": "green", "混乱": "red", "中立": "yellow"}


class MapView(Static):
    can_focus = True
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
            return "Loading..."
        gmap = self.state.map
        pc, pr = self.state.controlled_entity_pos
        r = self.state.controlled_entity.vision_range

        # 视口尺寸：基于视野范围对称计算（宽不再 ×2 避免晃动）
        vw = min(r * 2 + 3, gmap.width)
        vh = min(r * 2 + 3, gmap.height)
        ox = max(0, min(pc - vw // 2, gmap.width - vw))
        oy = max(0, min(pr - vh // 2, gmap.height - vh))

        # 观察模式 / 远程瞄准模式：视口扩展确保光标可见
        # 多格瞄准时所有光标格为锚格 + 形状偏移
        cursor_cells = set()
        if self.state.observe_mode:
            cursor_cells = {self.state.observe_cursor}
        elif self.state.combat_phase == "ranged_target":
            from domain.combat.shape import shape_cells, shape_from_pending_attack
            pa = self.state.pending_attack or {}
            shp = shape_from_pending_attack(pa)
            cursor_cells = set(shape_cells(self.state.observe_cursor, shp))
        if cursor_cells:
            oc, oro = self.state.observe_cursor
            ox = min(ox, oc)
            oy = min(oy, oro)
            ox = max(ox, oc - vw + 1)
            oy = max(oy, oro - vh + 1)
            ox = max(0, min(ox, gmap.width - vw))
            oy = max(0, min(oy, gmap.height - vh))

        text = Text()
        spatial_cache = self.state.spatial_cache()
        ground_items_by_position = spatial_cache["ground_items_by_position"]
        for row in range(oy, min(oy + vh, gmap.height)):
            for col in range(ox, min(ox + vw, gmap.width)):
                in_bright = (col, row) in self.state.fov_bright
                in_dim = (col, row) in self.state.fov_dim
                if not in_bright and not in_dim:
                    text.append(" ")
                    continue
                dim_style = " dim" if in_dim and not in_bright else ""
                cur = " reverse" if (col, row) in cursor_cells else ""
                t = gmap[col, row]
                # 地表叠加：燃烧 → 橙底；潮湿/水域 → 蓝底；雾气 → 白底（统一 is_burning/is_wet）
                overlay = ""
                if self.state.is_burning((col, row)):
                    overlay = " on rgb(180,80,20)"
                elif self.state.is_wet((col, row)):
                    overlay = " on rgb(20,60,120)"
                elif (col, row) in self.state.fog_surfaces:
                    overlay = " on rgb(200,200,200)"
                ent = self.state.get_entity_at(col, row)
                # 隐匿过滤：对玩家隐匿的实体不渲染（阶段4）
                if ent is not None and self.state.controlled_entity is not None and ent is not self.state.controlled_entity:
                    if self.state._is_hidden_to(self.state.controlled_entity, ent, (col, row)):
                        ent = None
                # 实体叠加：灼烧 → 橙底；潮湿 → 蓝底（与地表叠加对称）
                ent_overlay = ""
                if ent is not None:
                    if ent.has_status("灼烧"):
                        ent_overlay = " on rgb(180,80,20)"
                    elif ent.has_status("潮湿"):
                        ent_overlay = " on rgb(20,60,120)"
                elif self.state.controlled_entity is not None and self.state.controlled_entity.has_status("灼烧"):
                    ent_overlay = " on rgb(180,80,20)"
                elif self.state.controlled_entity is not None and self.state.controlled_entity.has_status("潮湿"):
                    ent_overlay = " on rgb(20,60,120)"
                if ent is not None:
                    if ent.controlled:
                        ch, color = "@", "green"
                    elif ent.is_dead:
                        ch, color = "%", FACTION_COLORS.get(ent.faction, "")
                    elif ent.has_status("濒死"):
                        ch, color = ent.char, "red"
                    else:
                        ch, color = ent.char, FACTION_COLORS.get(ent.faction, "")
                    text.append(ch, style=f"bold {color}{cur}{dim_style}{ent_overlay}" if ent.faction == "混乱" else f"{color}{cur}{dim_style}{ent_overlay}")
                elif (col, row) == (pc, pr):
                    text.append("@", style=f"bold bright_cyan{cur}{dim_style}{ent_overlay}")
                else:
                    # 陷阱/线索渲染（阶段5）：已发现/已触发的陷阱红 `;`，已发现的线索白 `:`（未发现不渲染）
                    if self.state._is_trap_visible((col, row)):
                        text.append(";", style=f"bold red{cur}{dim_style}{overlay}")
                    elif self.state._is_clue_visible((col, row)):
                        text.append(":", style=f"bold white{cur}{dim_style}{overlay}")
                    elif (col, row) in self.state.crops:
                        from domain.crops import crop_map_render
                        ch, color = crop_map_render(self.state.crops[(col, row)])
                        text.append(ch, style=f"bold {color}{cur}{dim_style}{overlay}")
                    else:
                        ground_at = get_ground_items_at(
                            ground_items_by_position.get((col, row), []), col, row
                        )
                        if ground_at:
                            # 统计不重复的 item_type
                            types_seen = set()
                            for g in ground_at:
                                types_seen.add(g["item_type"])
                            if len(types_seen) == 1:
                                # 同类物品 -> 显示该类型字符
                                ginfo = ground_at[0]
                                ch = ginfo["char"]
                                color = ginfo["color"]
                            else:
                                # 不同类 -> 显示类型数量
                                ch = str(len(types_seen))
                                color = "white"

                            text.append(ch, style=f"{color}{cur}{dim_style}{overlay}")
                        else:
                            # TERRAIN_CHARS/COLORS 统一渲染
                            ch = TERRAIN_CHARS.get(t, "?")
                            color = TERRAIN_COLORS.get(t, "")
                            text.append(ch, style=f"{color}{cur}{dim_style}{overlay}")
            if row < min(oy + vh, gmap.height) - 1:
                text.append("\n")
        return text
