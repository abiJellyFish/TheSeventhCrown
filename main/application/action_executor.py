"""行动验证与串行执行。"""

from domain.action import (
    Action, AttackAction, DoorAction, EatAction, EquipAction, HideAction,
    HarvestAction, LootAction, MoveAction, PickupAction, StandAction,
    StatusAction, WaitAction,
)
from domain.movement import can_enter
from domain.events import (
    damage_dealt,
    entity_died,
    item_equipped,
    item_picked_up,
    status_changed,
)


class ActionConflict(Exception):
    """行动基于过期状态，必须重新决策。"""


class ActionValidator:
    def validate(self, state, action: Action):
        if action.expected_state_version != state.state_version:
            raise ActionConflict("action state version is stale")
        actor = next((c for c, _ in state.entities if id(c) == action.actor_id), None)
        if actor is None or actor.is_dead:
            raise ActionConflict("action actor is unavailable")
        return actor


class ActionExecutor:
    """每次只提交一个行动；副作用由现有领域入口处理。"""

    def __init__(self, validator: ActionValidator | None = None) -> None:
        self.validator = validator or ActionValidator()

    def execute(self, state, action: Action) -> bool:
        actor = self.validator.validate(state, action)
        if isinstance(action, MoveAction):
            position = state.get_entity_pos(actor)
            if position is None:
                raise ActionConflict("action actor has no position")
            if not can_enter(
                *action.destination,
                state.map,
                state.entities,
                *position,
                ground_items=getattr(state, "ground_items", None),
            ):
                return False
            if actor is state.controlled_entity:
                return state.move_player(*action.destination)
            return state.move_entity(actor, *position, *action.destination)
        if isinstance(action, AttackAction):
            target = next(
                (creature for creature, _ in state.iter_entities()
                 if id(creature) == action.target_id),
                None,
            )
            if target is None:
                item_entry = next(
                    ((item, pos) for item, pos in state.ground_items
                     if id(item) == action.target_id),
                    None,
                )
                if item_entry is None:
                    raise ActionConflict("action target is unavailable")
                item, _ = item_entry
                item.durability = getattr(item, "durability", 1) - 1
                if item.durability <= 0:
                    state.ground_items.remove(item_entry)
                    state.invalidate_spatial_cache()
                state.state_version += 1
                return True
            if target.is_dead:
                raise ActionConflict("action target is unavailable")
            from domain.combat.attack import resolve_attack
            from domain.combat.opportunity import default_melee_weapon
            weapon = default_melee_weapon(actor)
            result = resolve_attack(
                actor,
                target,
                weapon,
                attacker_pos=state.get_entity_pos(actor),
                target_pos=state.get_entity_pos(target),
                grid=state.map,
                ground_items=getattr(state, "ground_items", []),
            )
            if result["damage"]:
                state.emit_event(damage_dealt(
                    id(actor), id(target), result["damage"], result["damage_type"],
                ))
            if target.is_dead:
                state.emit_event(entity_died(id(target), target.name))
            state.state_version += 1
            return True
        if isinstance(action, HideAction):
            result = state._do_hide(actor)
            if result:
                state.state_version += 1
            return result
        if isinstance(action, StandAction):
            result = state._do_stand(actor)
            if result:
                state.state_version += 1
            return result
        if isinstance(action, WaitAction):
            state.state_version += 1
            return True
        if isinstance(action, StatusAction):
            if action.remove:
                actor.remove_status(action.status)
            else:
                actor.add_status(action.status, action.duration)
            state.emit_event(status_changed(id(actor), action.status, not action.remove))
            state.state_version += 1
            return True
        if isinstance(action, DoorAction):
            door = next(
                (item for item, pos in state.ground_items
                 if pos == action.position
                 and item.name in ("打开的门", "关闭的门")),
                None,
            )
            if door is None or (action.opened == (door.name == "打开的门")):
                return False
            from domain.trade import load_item
            state.ground_items = [
                (item, pos) for item, pos in state.ground_items if item is not door
            ]
            replacement = load_item("打开的门" if action.opened else "关闭的门")
            if replacement is None:
                raise RuntimeError("缺少门状态物品")
            replacement.door_id = getattr(
                door, "door_id",
                f"{action.position[0]},{action.position[1]}",
            )
            state.ground_items.append((replacement, action.position))
            state.invalidate_spatial_cache()
            state.state_version += 1
            return True
        if isinstance(action, PickupAction):
            entry = next(
                ((item, pos) for item, pos in state.ground_items
                 if id(item) == action.item_id and pos == action.position),
                None,
            )
            if entry is None:
                if action.item is None:
                    return False
                actor.inventory.append(action.item)
                state.emit_event(item_picked_up(id(actor), action.item.name, action.position))
                state.state_version += 1
                return True
            item, _ = entry
            state.ground_items.remove(entry)
            actor.inventory.append(item)
            state.emit_event(item_picked_up(id(actor), item.name, action.position))
            state.state_version += 1
            return True
        if isinstance(action, EatAction):
            if action.item_id is None and action.position is not None:
                bush = next(
                    (item for item, position in state.ground_items
                     if position == action.position and "灌木" in item.name),
                    None,
                )
                if bush is None:
                    return False
                from domain.trade import load_item
                import random
                berry = load_item("浆果")
                amount = int(berry.amount) if berry else 750
                actor.food_value = min(
                    15000, actor.food_value + random.randint(2, 5) * amount
                )
                state.harvested_bushes[action.position] = state.clock.pendulum_count + 6
                state.state_version += 1
                return True
            if action.item_id is None:
                return False
            item = next(
                (candidate for candidate in actor.inventory
                 if id(candidate) == action.item_id),
                None,
            )
            if item is None or getattr(item, "effect", "") != "restore_food":
                return False
            try:
                amount = int(item.amount)
            except (ValueError, TypeError):
                amount = 2000
            actor.food_value = min(15000, actor.food_value + amount)
            if item.count > 1:
                item.count -= 1
            else:
                actor.inventory.remove(item)
            state.state_version += 1
            return True
        if isinstance(action, EquipAction):
            item = next(
                (candidate for candidate in actor.inventory
                 if id(candidate) == action.item_id),
                None,
            )
            if item is None:
                return False
            slot = action.slot
            if slot is None:
                slot = getattr(item, "slot", None)
                if slot is None and getattr(item, "weapon", None) is not None:
                    slot = next(
                        (candidate for candidate in ("right_hand", "left_hand")
                         if actor.equipment.get(candidate) is None),
                        None,
                    )
            if slot is None or actor.equipment.get(slot) is not None:
                return False
            actor.equipment[slot] = item
            actor.inventory.remove(item)
            state.emit_event(item_equipped(id(actor), item.name, slot))
            state.state_version += 1
            return True
        if isinstance(action, LootAction):
            target = next(
                (candidate for candidate, _ in state.iter_entities()
                 if id(candidate) == action.target_id),
                None,
            )
            if target is None or not target.is_dead:
                return False
            state._resolve_hunt_loot(actor, target, 15000)
            state.state_version += 1
            return True
        if isinstance(action, HarvestAction):
            from domain.trade import load_item
            import random
            berry = load_item("浆果")
            if berry is None:
                return False
            berry.count = random.randint(2, 5)
            actor.inventory.append(berry)
            state.harvested_bushes[action.position] = state.clock.pendulum_count + 6
            state.state_version += 1
            return True
        raise NotImplementedError(type(action).__name__)
