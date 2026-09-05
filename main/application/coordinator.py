"""Textual 与领域层之间的应用协调器。

该模块只负责协调流程和刷新通知，不实现战斗规则。
"""
from dataclasses import dataclass
from typing import Callable, Protocol

from domain.action import Action, MoveAction, WaitAction
from domain.game_state import GameState
from application.action_executor import ActionConflict, ActionExecutor
from domain.events import (
    DamageDealt,
    EntityDied,
    LogCategory,
    StatusChanged,
)


class LogPort(Protocol):
    def add(self, message: str) -> None: ...


class InputPort(Protocol):
    def focus(self) -> None: ...


class RefreshPort(Protocol):
    def __call__(self) -> None: ...


@dataclass
class UIContext:
    """控制器使用的显式 UI 依赖。"""

    game: GameState
    log: LogPort
    combat_log: LogPort | None = None
    input: InputPort | None = None
    refresh: RefreshPort | None = None
    event_handlers: dict[str, Callable[[object], None]] | None = None


class ApplicationCoordinator:
    """应用流程边界，保留现有 GameState 流程作为兼容实现。"""

    def __init__(self, context: UIContext):
        self.context = context
        if self.game.action_executor is None:
            self.game.action_executor = ActionExecutor()

    @property
    def game(self) -> GameState:
        return self.context.game

    def refresh(self) -> None:
        if self.context.refresh is not None:
            self.context.refresh()

    def _render_combat_event(self, event) -> str | None:
        """将结构化战斗事件转换为战斗日志文本。"""
        if isinstance(event, DamageDealt):
            names = {
                id(creature): creature.name
                for creature, _ in self.game.iter_entities()
            }
            attacker = names.get(event.attacker_id, "未知实体")
            target = names.get(event.target_id, "未知实体")
            return f"{attacker}攻击{target}，造成 {event.amount} 点伤害"
        if isinstance(event, EntityDied):
            return f"{event.entity_name}死亡"
        if isinstance(event, StatusChanged):
            action = "获得" if event.active else "失去"
            names = {
                id(creature): creature.name
                for creature, _ in self.game.iter_entities()
            }
            return f"{names.get(event.entity_id, '未知实体')}{action}状态：{event.status}"
        return None

    def _position_is_visible(self, position) -> bool:
        """判断日志位置是否在玩家当前视野内。"""
        if position is None:
            return True
        if self.game.controlled_entity is None:
            return True
        player_position = self.game.controlled_entity_pos
        pos3 = (*position[:2], position[2]) if len(position) == 3 else (*position, self.game.active_z)
        return pos3[:2] == player_position[:2] or self.game.is_in_fov(pos3)

    def _entity_position_by_id(self, entity_id: int):
        """按稳定的运行时实体 ID 查找事件位置。"""
        return next(
            (position for entity, position in self.game.iter_entities()
             if id(entity) == entity_id),
            None,
        )

    def _event_is_visible(self, event) -> bool:
        """按事件来源位置过滤远离玩家视野的领域日志。"""
        position = event.payload.get("position")
        if event.name == "LogEvent":
            return self._position_is_visible(position)
        if isinstance(event, DamageDealt):
            positions = (
                self._entity_position_by_id(event.attacker_id),
                self._entity_position_by_id(event.target_id),
            )
            return any(self._position_is_visible(item) for item in positions)
        if isinstance(event, (EntityDied, StatusChanged)):
            return self._position_is_visible(
                self._entity_position_by_id(event.entity_id)
            )
        return True

    def consume_events(self, *, notify: bool = True):
        """消费领域事件；UI 只通过此入口获得统一刷新通知。"""
        events = self.game.drain_events()
        for event in events:
            if not self._event_is_visible(event):
                continue
            if event.name == "LogEvent":
                category = event.payload.get("category", LogCategory.SYSTEM.value)
                target = (
                    self.context.combat_log
                    if category == LogCategory.COMBAT.value
                    and self.context.combat_log is not None
                    else self.context.log
                )
                target.add(event.payload["message"])
            else:
                combat_message = self._render_combat_event(event)
                if combat_message is not None and self.context.combat_log is not None:
                    self.context.combat_log.add(combat_message)
            handler = (self.context.event_handlers or {}).get(event.name)
            if handler is not None:
                handler(event)
        if events and notify:
            self.refresh()
        return events

    def log(
        self, message: str, category: LogCategory = LogCategory.SYSTEM,
    ) -> None:
        target = (
            self.context.combat_log
            if category is LogCategory.COMBAT and self.context.combat_log is not None
            else self.context.log
        )
        target.add(message)

    def submit_action(self, action: Action) -> bool | None:
        """统一提交领域动作，具体规则仍由 GameState/ActionExecutor 执行。"""
        if not hasattr(action, "expected_state_version"):
            raise TypeError("action must be a domain.action.Action")
        self.game.submit_action(action)
        try:
            result = self.game.execute_next_action()
        except ActionConflict:
            # 若受控者已死，说明小队已全灭，应让结束页流程接管，不再提示
            actor = next(
                (c for c, _ in self.game.entities if id(c) == action.actor_id), None
            )
            if actor is None or actor.is_dead:
                if self.game.is_game_over():
                    return False
            self.log("行动已失效，请重新操作")
            return False
        self.consume_events(notify=False)
        return result

    def execute_operation(self, operation: Callable[[], object]) -> object:
        """统一承接尚未迁移到 Action 的旧领域流程。"""
        result = operation()
        self.consume_events(notify=False)
        return result

    def move(self, destination: tuple[int, int]) -> bool | None:
        player = self.game.controlled_entity
        if player is None:
            return None
        return self.submit_action(
            MoveAction(
                actor_id=id(player),
                expected_state_version=self.game.state_version,
                destination=destination,
            )
        )

    def wait(self) -> bool | None:
        player = self.game.controlled_entity
        if player is None:
            return None
        return self.submit_action(
            WaitAction(
                actor_id=id(player),
                expected_state_version=self.game.state_version,
            )
        )

    def rest(self, operation: Callable[[], object]) -> object:
        return self.execute_operation(operation)

    def end_turn(self, operation: Callable[[], object]) -> object:
        return self.execute_operation(operation)

    def set_callbacks(
        self,
        *,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        if on_refresh is not None:
            self.context.refresh = on_refresh
