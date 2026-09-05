"""只读 UI 展示模型。"""
from dataclasses import dataclass

from domain.game_state import GameState


@dataclass(frozen=True)
class PlayerViewModel:
    name: str
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    ap: int
    max_ap: int
    level: int
    class_name: str


@dataclass(frozen=True)
class CombatViewModel:
    in_combat: bool
    phase: str
    turn_name: str | None


@dataclass(frozen=True)
class MapViewModel:
    player_position: tuple[int, int, int]
    visible_tiles: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class CookingToolViewModel:
    name: str
    tool_type: str
    position: tuple[int, int]


@dataclass(frozen=True)
class GameViewModel:
    player: PlayerViewModel
    combat: CombatViewModel
    map: MapViewModel
    snapshot: GameState
    cooking_tools: tuple[CookingToolViewModel, ...] = ()
    selected_cooking_tool: CookingToolViewModel | None = None


def build_game_view_model(
    state: GameState,
    *,
    cooking_tools: tuple[CookingToolViewModel, ...] = (),
    selected_cooking_tool: CookingToolViewModel | None = None,
) -> GameViewModel:
    """构建 UI 快照。直接引用 live GameState，避免每帧 deepcopy。"""
    player = state.controlled_entity
    return GameViewModel(
        player=PlayerViewModel(
            name=player.name,
            hp=player.hp,
            max_hp=player.max_hp,
            mp=player.mp,
            max_mp=player.max_mp,
            ap=player.ap,
            max_ap=player.max_ap,
            level=player.class_level,
            class_name=player.char_class,
        ),
        combat=CombatViewModel(
            in_combat=state.in_combat,
            phase=state.combat_phase,
            turn_name=(
                state.combat_turn_entity.name
                if state.combat_turn_entity is not None
                else None
            ),
        ),
        map=MapViewModel(
            player_position=state.controlled_entity_pos,
            visible_tiles=frozenset(state.fov_cache),
        ),
        snapshot=state,
        cooking_tools=cooking_tools,
        selected_cooking_tool=selected_cooking_tool,
    )
