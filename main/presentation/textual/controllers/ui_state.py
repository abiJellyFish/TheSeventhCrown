"""统一的 UI 状态投影。"""
from dataclasses import dataclass

from domain.game_state import GameState

_COMMON_KEYS = frozenset({"X", "C", "I", "B", "E"})
_COMBAT_KEYS = frozenset({"A", "S", "N", "enter", "apostrophe"})

# 与 LeftPanel.render / GameScreen._INTERACT_VIEWS 分支顺序一致
_INTERACT_VIEWS = {
    "menu": "interact_menu",
    "item_menu": "item_menu",
    "target": "target",
    "trading": "trading",
    "cook_pick": "cook_pick",
    "cook_tool": "cook_tool",
    "cook_confirm": "cook_confirm",
    "craft_list": "craft_list",
    "craft_tool": "craft_tool",
    "craft_product": "craft_product",
    "craft_continue": "craft_continue",
    "craft_adv_select": "craft_adv_select",
    "chest": "chest",
    "chest_take_qty": "chest_qty",
    "chest_store_qty": "chest_qty",
    "action_menu": "action_menu",
    "shove_choice": "shove_choice",
    "looting": "looting",
    "reaction": "reaction",
    "stealing": "stealing",
    "steal_caught": "steal_caught",
    "party_select": "party_select",
    "party_dismiss": "party_dismiss",
    "rest_select": "rest_select",
}

# 左栏主面板：快捷键直接触发，不自动唤起输入框
_LEFT_NO_INPUT = frozenset({"explore", "combat_idle", "combat_ranged_target"})


@dataclass(frozen=True)
class UIState:
    left_view: str
    right_view: str
    input_enabled: bool
    allowed_keys: frozenset[str]


def resolve_left_view(state: GameState) -> str:
    """左栏当前视图名，与 LeftPanel.render 分支一致。"""
    ip = state.interact_phase
    if ip:
        return _INTERACT_VIEWS.get(ip, ip)
    cp = state.combat_phase
    if cp != "idle":
        return f"combat_{cp}"
    return "combat_idle" if state.in_combat else "explore"


def resolve_right_view(state: GameState, panel_view_mode: str = "default") -> str:
    """右栏当前视图名。"""
    if state.item_menu_stack:
        return "item_menu"
    if state.observe_mode:
        return "observe"
    return panel_view_mode


def build_ui_state(state: GameState, right_view: str = "default") -> UIState:
    left_view = resolve_left_view(state)
    right_view = resolve_right_view(state, right_view)

    # 输入框仅由左栏流程决定；右栏单独打开不抢占左栏主面板快捷键
    input_enabled = left_view not in _LEFT_NO_INPUT
    if (
        state.combat_phase == "ranged_target"
        and (state.pending_attack or {}).get("target_choice_active")
    ):
        input_enabled = True
    # 物品交互菜单栈：即使左栏在主面板，仍需输入命令
    if state.item_menu_stack:
        input_enabled = True

    return UIState(
        left_view=left_view,
        right_view=right_view,
        input_enabled=input_enabled,
        allowed_keys=(
            _COMMON_KEYS
            | (_COMBAT_KEYS if state.in_combat else frozenset())
        ),
    )
