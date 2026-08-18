"""地图视图 —— 单字符 ASCII 渲染，FOV 裁剪，动态图例。"""

from rich.text import Text
from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain
from core.item_actions import GROUND_ITEM_RENDER, get_ground_items_at

TERRAIN_COLORS = {
    Terrain.GRASS:        "rgb(140,210,120)",
    Terrain.BARREN:       "rgb(150,150,150)",
    Terrain.PLAIN:        "rgb(200,200,100)",
    Terrain.FLOOR:        "rgb(60,60,60)",
    Terrain.WATER:        "rgb(100,160,255)",
    Terrain.BUSH:         "green",
    Terrain.STONE:        "rgb(128,128,128)",
    Terrain.TREE:         "rgb(139,90,43)",
    Terrain.LOW_WALL:     "rgb(180,180,180)",
    Terrain.BED:          "cyan",
    Terrain.CAMPFIRE:     "red",
    Terrain.DOOR:         "yellow",
    Terrain.STAIRS_DOWN:  "magenta",
    Terrain.STAIRS_UP:    "magenta",
    Terrain.WALL:         "rgb(140,140,140)",
}
TERRAIN_CHARS = {
    Terrain.GRASS:        ".",
    Terrain.BARREN:       ".",
    Terrain.PLAIN:        ".",
    Terrain.FLOOR:        ".",
    Terrain.WATER:        "^",
    Terrain.BUSH:         '"',
    Terrain.STONE:        "o",
    Terrain.TREE:         "T",
    Terrain.LOW_WALL:     "=",
    Terrain.BED:          "=",
    Terrain.CAMPFIRE:     "=",
    Terrain.DOOR:         "+",
    Terrain.STAIRS_DOWN:  ">",
    Terrain.STAIRS_UP:    "<",
    Terrain.WALL:         "#",
}
FACTION_COLORS = {"守序": "green", "混乱": "red", "中立": "yellow"}


class MapView(Static):
    can_focus = True
    state: GameState | None = None

    def render(self) -> str:
        if self.state is None:
            return "Loading..."
        gmap = self.state.map
        pc, pr = self.state.player_pos
        r = self.state.player.vision_range

        # 视口尺寸：基于视野范围对称计算（宽不再 ×2 避免晃动）
        vw = min(r * 2 + 3, gmap.width)
        vh = min(r * 2 + 3, gmap.height)
        ox = max(0, min(pc - vw // 2, gmap.width - vw))
        oy = max(0, min(pr - vh // 2, gmap.height - vh))

        # 观察模式 / 远程瞄准模式：视口扩展确保光标可见
        obs_cur = None
        if self.state.observe_mode:
            obs_cur = self.state.observe_cursor
        elif self.state.combat_phase == "ranged_target":
            obs_cur = self.state.observe_cursor
        if obs_cur is not None:
            oc, oro = obs_cur
            ox = min(ox, oc)
            oy = min(oy, oro)
            ox = max(ox, oc - vw + 1)
            oy = max(oy, oro - vh + 1)
            ox = max(0, min(ox, gmap.width - vw))
            oy = max(0, min(oy, gmap.height - vh))

        text = Text()
        for row in range(oy, min(oy + vh, gmap.height)):
            for col in range(ox, min(ox + vw, gmap.width)):
                in_bright = (col, row) in self.state.fov_bright
                in_dim = (col, row) in self.state.fov_dim
                if not in_bright and not in_dim:
                    text.append(" ")
                    continue
                dim_style = " dim" if in_dim and not in_bright else ""
                cur = " reverse" if (col, row) == obs_cur else ""
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
                if ent is not None and self.state.player is not None and ent is not self.state.player:
                    if self.state._is_hidden_to(self.state.player, ent, (col, row)):
                        ent = None
                # 实体叠加：灼烧 → 橙底；潮湿 → 蓝底（与地表叠加对称）
                ent_overlay = ""
                if ent is not None:
                    if ent.has_status("灼烧"):
                        ent_overlay = " on rgb(180,80,20)"
                    elif ent.has_status("潮湿"):
                        ent_overlay = " on rgb(20,60,120)"
                elif self.state.player is not None and self.state.player.has_status("灼烧"):
                    ent_overlay = " on rgb(180,80,20)"
                elif self.state.player is not None and self.state.player.has_status("潮湿"):
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
                    # 门：检查 door_states 区分开/关
                    elif (col, row) in self.state.door_states:
                        is_open = self.state.door_states[(col, row)]
                        ch = "_" if is_open else "]"
                        text.append(ch, style=f"bold yellow{cur}{dim_style}{overlay}")
                    else:
                        # 检查地上物品（提前计算供后续判断）
                        ground_at = get_ground_items_at(self.state.ground_items, col, row)
                        # 检查箱子
                        if (col, row) in self.state.chests:
                            text.append("$", style=f"bold yellow{cur}{dim_style}{overlay}")
                        # 检查地上物品
                        elif ground_at:
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
                            if t == Terrain.CAMPFIRE and not self.state.is_burning((col, row)):
                                color = "dark_red"  # 未燃篝火：暗灰/暗红显示结构，无橙底
                            text.append(ch, style=f"{color}{cur}{dim_style}{overlay}")
            if row < min(oy + vh, gmap.height) - 1:
                text.append("\n")
        return text
