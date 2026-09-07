"""烹饪 / 制作 / 炼药面板。不进 ActionExecutor。"""
from domain.craft.engine import (
    complete_recipe,
    continue_make,
    count_named,
    finish_from_materials,
    start_make,
)
from domain.craft.recipe import (
    ALCH_INGREDIENTS,
    BY_CRAFT,
    COOK_INGREDIENTS,
    HANDS,
    recipe_by_id,
)
from domain.craft.stations import available_tools
from domain.trade import load_item, price_to_text

CRAFT_PHASES = frozenset({
    "cook_pick", "cook_tool", "cook_confirm",
    "craft_list", "craft_tool", "craft_product", "craft_adv_select", "craft_continue",
})

_KIND_TITLE = {"cook": "烹饪", "alchemy": "炼药", "make": "制作"}
_MAKE_TOOLS = ("皮革工具",)
_ALCH_TOOLS = ("捣药钵",)


def is_craft_phase(phase: str) -> bool:
    return phase in CRAFT_PHASES


class CraftMixin:
    def _craft_reset(self) -> None:
        self._craft_kind = ""
        self._pick = {}
        self._pick_names = []
        self._selected_tool = HANDS
        self._craft_product = ""
        self._continue_item = None
        self._craft_faces = []
        self._craft_pending = None
        if self._state is not None:
            self._state.pending_craft = {}

    def _craft_sync(self) -> None:
        if self._state is None:
            return
        self._state.pending_craft = {
            "kind": getattr(self, "_craft_kind", ""),
            "pick": dict(getattr(self, "_pick", {})),
            "pick_names": list(getattr(self, "_pick_names", [])),
            "tool": getattr(self, "_selected_tool", HANDS),
            "product": getattr(self, "_craft_product", ""),
            "rolls": list(getattr(self, "_craft_faces", [])),
            "continue_name": getattr(getattr(self, "_continue_item", None), "name", ""),
            "continue_progress": getattr(getattr(self, "_continue_item", None), "craft_progress", 0),
            "continue_required": getattr(getattr(self, "_continue_item", None), "craft_required", 0),
        }

    def action_cooking(self):
        self._open_material_flow("cook")

    def action_alchemy(self):
        self._open_material_flow("alchemy")

    def action_crafting(self):
        self._craft_reset()
        self._craft_kind = "make"
        self._state.interact_phase = "craft_list"
        self._craft_sync()
        self.refresh_all()
        self._wake_input()

    def _open_material_flow(self, kind: str) -> None:
        self._craft_reset()
        self._craft_kind = kind
        self._pick_names = _list_ingredients(self._state.controlled_entity, kind)
        self._state.interact_phase = "cook_pick"
        self._craft_sync()
        self.refresh_all()
        self._wake_input()

    def _craft_enter(self) -> None:
        ip = self._state.interact_phase
        if ip == "cook_pick":
            if sum(self._pick.values()) <= 0:
                self._act_log.add("还没有选择材料")
                return
            self._open_tool_panel()
            return
        if ip == "cook_tool":
            self._state.interact_phase = "cook_confirm"
            self._craft_sync()
            self.refresh_all()
            return
        if ip == "cook_confirm":
            self._confirm_material_craft()
            return
        if ip == "craft_tool":
            self._state.interact_phase = "craft_product"
            self._craft_sync()
            self.refresh_all()

    def _craft_back(self) -> None:
        ip = self._state.interact_phase
        if ip == "craft_adv_select":
            self._act_log.add("必须选择一颗骰面以完成检定")
            return
        back = {
            "cook_pick": "",
            "cook_tool": "cook_pick",
            "cook_confirm": "cook_tool",
            "craft_list": "",
            "craft_tool": "craft_list",
            "craft_product": "craft_tool",
            "craft_continue": "",
        }.get(ip, "")
        if back == "":
            self._craft_reset()
            self._state.interact_phase = ""
        else:
            self._state.interact_phase = back
            self._craft_sync()
        self.refresh_all()

    def _open_tool_panel(self) -> None:
        names = _MAKE_TOOLS if self._craft_kind == "make" else (
            _ALCH_TOOLS if self._craft_kind == "alchemy" else ()
        )
        pos = self._state.controlled_entity_pos
        self._craft_tools = available_tools(self._state, pos, names)
        self._selected_tool = HANDS
        self._state.interact_phase = (
            "craft_tool" if self._craft_kind == "make" else "cook_tool"
        )
        self._craft_sync()
        self.refresh_all()
        self._wake_input()

    def _craft_cmd_pick(self, cmd: str) -> None:
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: 序号选择一份材料")
            return
        names = self._pick_names
        if num < 1 or num > len(names):
            self._act_log.add("材料序号无效")
            return
        name = names[num - 1]
        if sum(self._pick.values()) >= 5:
            self._act_log.add("最多选择 5 份材料")
            return
        if self._pick.get(name, 0) >= count_named(self._state.controlled_entity, name):
            self._act_log.add("背包里没有更多这份材料")
            return
        self._pick[name] = self._pick.get(name, 0) + 1
        self._craft_sync()
        self.refresh_all()

    def _craft_cmd_tool(self, cmd: str) -> None:
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: 序号选择工具")
            return
        tools = getattr(self, "_craft_tools", [HANDS])
        if num < 1 or num > len(tools):
            self._act_log.add("工具序号无效")
            return
        self._selected_tool = tools[num - 1]
        self._state.interact_phase = (
            "craft_product" if self._craft_kind == "make" else "cook_confirm"
        )
        self._craft_sync()
        self.refresh_all()

    def _confirm_material_craft(self) -> None:
        player = self._state.controlled_entity
        try:
            outcome = finish_from_materials(
                self._state, player, self._craft_kind,
                dict(self._pick), self._selected_tool, face_index=None,
            )
        except ValueError as exc:
            self._act_log.add(str(exc))
            return
        self._finish_outcome(outcome)

    def _craft_cmd_list(self, cmd: str) -> None:
        try:
            num = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :Z序号")
            return
        recipes = _known_make_recipes(self._state.controlled_entity)
        if num < 1 or num > len(recipes):
            self._act_log.add("成品序号无效")
            return
        self._craft_product = recipes[num - 1].output[0]
        self._open_tool_panel()

    def _craft_cmd_work(self, cmd: str) -> None:
        try:
            pendulums = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :Z钟摆数")
            return
        tool = getattr(self, "_selected_tool", HANDS)
        try:
            outcome = start_make(
                self._state, self._state.controlled_entity,
                self._craft_product, tool, pendulums, selected=None,
            )
        except ValueError as exc:
            self._act_log.add(str(exc))
            return
        self._finish_outcome(outcome)

    def _craft_cmd_continue(self, cmd: str) -> None:
        try:
            pendulums = int(cmd[1:])
        except (ValueError, IndexError):
            self._act_log.add("用法: :Z钟摆数")
            return
        item = self._continue_item
        if item is None:
            self._act_log.add("没有未完成物")
            return
        try:
            outcome = continue_make(
                self._state, self._state.controlled_entity, item, pendulums,
                selected=None,
            )
        except ValueError as exc:
            self._act_log.add(str(exc))
            return
        self._finish_outcome(outcome)

    def _open_craft_continue(self, item) -> None:
        self._craft_reset()
        self._continue_item = item
        self._state.interact_phase = "craft_continue"
        self._craft_sync()
        self.refresh_all()
        self._wake_input()

    def _cmd_craft_adv_select(self, cmd: str) -> None:
        try:
            num = int(cmd)
        except ValueError:
            self._act_log.add("输入序号选择骰面")
            return
        pending = self._craft_pending
        if pending is None or num < 1 or num > len(pending.faces):
            self._act_log.add("骰面序号无效")
            return
        player = self._state.controlled_entity
        unfinished = pending.unfinished
        if unfinished is not None:
            player.inventory = [item for item in player.inventory if item is not unfinished]
        recipe = recipe_by_id(pending.recipe_id)
        outcome = complete_recipe(
            player, recipe, pending.tool_name,
            faces=pending.faces, selected=num - 1, state=self._state,
        )
        self._finish_outcome(outcome)

    def _finish_outcome(self, outcome) -> None:
        if outcome.needs_select:
            self._craft_pending = outcome
            self._craft_faces = list(outcome.faces)
            self._state.interact_phase = "craft_adv_select"
            self._craft_sync()
            self.refresh_all()
            self._wake_input()
            return
        if outcome.product is not None:
            self._act_log.add(
                f"完成{_KIND_TITLE.get(self._craft_kind, '')}: "
                f"{outcome.product.name}（{outcome.quality}）"
            )
        elif outcome.unfinished is not None:
            self._act_log.add(
                f"制作中 {outcome.unfinished.craft_progress}/"
                f"{outcome.unfinished.craft_required}"
            )
        self._craft_reset()
        self._state.interact_phase = ""
        self.refresh_all()


def _list_ingredients(player, kind: str) -> list[str]:
    allowed = COOK_INGREDIENTS if kind == "cook" else ALCH_INGREDIENTS
    names = []
    for item in player.inventory:
        if item.name in allowed and item.name not in names:
            names.append(item.name)
    return names


def _known_make_recipes(player) -> list:
    recipes = []
    for recipe in BY_CRAFT.get("make", ()):
        if recipe.id in player.known_recipes:
            recipes.append(recipe)
    return recipes


def item_quality_label(item) -> str:
    if getattr(item, "unfinished", False):
        return item.name
    quality = getattr(item, "quality", "") or "普通"
    return f"{item.name}（{quality}）"


def item_info_text(name: str, count: int = 1) -> str:
    item = load_item(name)
    if item is None:
        return f"{name} x{count}"
    price = price_to_text(item.price) if item.price else "无价"
    return f"{item_quality_label(item)} x{count}  {item.description}  {price}"
