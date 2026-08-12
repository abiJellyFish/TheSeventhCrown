"""地图视图 —— 单字符 ASCII 渲染，FOV 裁剪，动态图例。"""

from rich.text import Text
from textual.widgets import Static

from core.game_state import GameState
from core.movement import Terrain
from core.item_actions import GROUND_ITEM_RENDER, get_ground_items_at

TERRAIN_COLORS = {
    Terrain.PASSABLE: "rgb(80,80,80)",
    Terrain.DIFFICULT: "green",
    Terrain.WALL: "rgb(140,140,140)",
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
                ent = self.state.get_entity_at(col, row)
                if ent is not None:
                    if ent.controlled:
                        ch, color = "@", "green"
                    elif ent.hp <= 0:
                        ch, color = "%", FACTION_COLORS.get(ent.faction, "")
                    else:
                        ch, color = ent.char, FACTION_COLORS.get(ent.faction, "")
                    text.append(ch, style=f"bold {color}{cur}{dim_style}" if ent.faction == "混乱" else f"{color}{cur}{dim_style}")
                elif (col, row) == (pc, pr):
                    text.append("@", style=f"bold bright_cyan{cur}{dim_style}")
                elif (col, row) in self.state.bed_positions:
                    text.append("=", style=f"bold cyan{cur}{dim_style}")
                elif (col, row) in self.state.stone_positions:
                    text.append("o", style=f"bold rgb(180,180,180){cur}{dim_style}")
                elif (col, row) in self.state.campfire_positions:
                    text.append("~", style=f"bold red{cur}{dim_style}")
                elif self.state.dungeon_entrance and (col, row) == self.state.dungeon_entrance:
                    text.append(">", style=f"bold magenta{cur}{dim_style}")
                else:
                    t = gmap[col, row]
                    if (col, row) in self.state.door_states:
                        is_open = self.state.door_states[(col, row)]
                        ch = "_" if is_open else "]"
                        text.append(ch, style=f"bold yellow{cur}{dim_style}")
                    else:
                        # 检查地上物品（提前计算供后续判断）
                        ground_at = get_ground_items_at(self.state.ground_items, col, row)
                        # 检查箱子
                        if (col, row) in self.state.chests:
                            text.append("$", style=f"bold yellow{cur}{dim_style}")
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

                            text.append(ch, style=f"{color}{cur}{dim_style}")
                        else:
                            ch = {Terrain.WALL: "#", Terrain.DIFFICULT: '"', Terrain.PASSABLE: "."}[t]
                            color = TERRAIN_COLORS.get(t, '')
                            text.append(ch, style=f"{color}{cur}{dim_style}")
            if row < min(oy + vh, gmap.height) - 1:
                text.append("\n")
        return text
