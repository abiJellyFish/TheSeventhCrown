"""制作开工/推进；烹饪炼药一次完成。"""
from dataclasses import dataclass, field

from domain.craft.recipe import (
    Recipe,
    effective_required,
    make_recipe_by_output,
    match_from_materials,
    recipe_by_id,
    time_for_tool,
)
from domain.craft.skills import (
    craft_level,
    grant_craft_exp,
    grant_tool_exp,
    quality_from_face,
    roll_faces,
)
from domain.loot import grant_item
from domain.trade import load_item


@dataclass
class CraftOutcome:
    unfinished: object | None = None
    product: object | None = None
    faces: list[int] = field(default_factory=list)
    needs_select: bool = False
    quality: str | None = None
    recipe_id: str = ""
    tool_name: str = ""
    halve: bool = False


def count_named(player, name: str) -> int:
    return sum(item.count for item in player.inventory if item.name == name)


def consume_named(player, need: dict[str, int]) -> None:
    for name, qty in need.items():
        left = qty
        for item in list(player.inventory):
            if left <= 0:
                break
            if item.name != name or getattr(item, "unfinished", False):
                continue
            take = min(item.count, left)
            unit = item.weight / item.count if item.count else 0
            item.count -= take
            item.weight -= unit * take
            left -= take
            if item.count <= 0:
                player.inventory.remove(item)
        if left > 0:
            raise ValueError(f"材料不足: {name}")


def spend_pendulums(state, player, n: int) -> None:
    if n < 0:
        raise ValueError("钟摆数不能为负")
    if n == 0:
        return
    if state.in_combat:
        cost = n * state.clock.scale
        if player.ap < cost:
            raise ValueError("剩余ap不足")
        player.ap -= cost
        return
    state.clock.tick_action(float(n))


def _require_make_ticks(state, player, pendulums: int, remaining: int) -> None:
    if pendulums < 0:
        raise ValueError("钟摆数不能为负")
    if pendulums > remaining:
        raise ValueError("超过最大时间")
    if state.in_combat:
        cost = pendulums * state.clock.scale
        if player.ap < cost:
            raise ValueError("剩余ap不足")


def _tool_category(recipe: Recipe, tool_name: str) -> str:
    for spec in recipe.tools:
        if spec.name == tool_name:
            return spec.category
    return ""


def _learn(player, recipe: Recipe) -> None:
    if recipe.id in player.known_recipes:
        return
    player.recipe_attempts[recipe.id] = player.recipe_attempts.get(recipe.id, 0) + 1
    if player.recipe_attempts[recipe.id] >= recipe.discovery_needed:
        player.known_recipes.append(recipe.id)


def _make_product(recipe: Recipe, quality: str):
    product = load_item(recipe.output[0])
    if product is None:
        raise ValueError(f"成品不存在: {recipe.output[0]}")
    product.count = recipe.output[1]
    if product.weight:
        product.weight = product.weight * product.count
    product.quality = quality
    extra = list(getattr(product, "quality_traits", {}).get(quality, []))
    product.traits = list(product.traits) + extra
    return product


def resolve_check(player, recipe: Recipe, tool_name: str, *, faces=None, selected=None) -> CraftOutcome:
    known = recipe.id in player.known_recipes
    halve = recipe.craft == "alchemy" and not known
    category = _tool_category(recipe, tool_name)
    if faces is None:
        advantage = 0
        if category:
            advantage = (
                player.tool_proficiency_level(category)
                + player.tool_expertise_level(category)
            )
        faces = roll_faces(advantage)
    if len(faces) > 1 and selected is None:
        return CraftOutcome(
            faces=list(faces), needs_select=True,
            recipe_id=recipe.id, tool_name=tool_name, halve=halve,
        )
    index = 0 if selected is None else int(selected)
    face = faces[index]
    quality = quality_from_face(face, craft_level(player, recipe.craft), halve=halve)
    return CraftOutcome(
        faces=list(faces), quality=quality, recipe_id=recipe.id,
        tool_name=tool_name, halve=halve,
    )


def complete_recipe(player, recipe: Recipe, tool_name: str, *, faces=None, selected=None, state=None) -> CraftOutcome:
    outcome = resolve_check(player, recipe, tool_name, faces=faces, selected=selected)
    if outcome.needs_select:
        return outcome
    product = _make_product(recipe, outcome.quality)
    grant_craft_exp(player, recipe.craft, 0.1)
    category = _tool_category(recipe, tool_name)
    if category:
        grant_tool_exp(player, category, 0.1)
    _learn(player, recipe)
    grant_item(player, product, state)
    outcome.product = product
    return outcome


def apply_selected_face(player, recipe: Recipe, tool_name: str, faces: list[int], index: int) -> CraftOutcome:
    return complete_recipe(player, recipe, tool_name, faces=faces, selected=index)


def _unfinished_item(recipe: Recipe, tool_name: str, required: int):
    product = load_item(recipe.output[0])
    if product is None:
        raise ValueError(f"成品不存在: {recipe.output[0]}")
    return type(product)(
        name=f"未完成的{recipe.output[0]}",
        item_type=dict(product.item_type),
        weight=product.weight,
        description=f"尚未完成的{recipe.output[0]}",
        unfinished=True,
        recipe_id=recipe.id,
        craft_tool=tool_name,
        craft_required=required,
        craft_progress=0,
        durability=product.durability,
        max_durability=product.max_durability,
        armor=product.armor,
        weapon=product.weapon,
    )


def _advance_unfinished(state, player, unfinished, ticks: int) -> int:
    remaining = unfinished.craft_required - unfinished.craft_progress
    if ticks > remaining:
        raise ValueError("超过最大时间")
    if state.in_combat:
        spend_pendulums(state, player, ticks)
        unfinished.craft_progress += ticks
        return ticks
    hp = player.hp
    progressed = 0
    for _ in range(ticks):
        state.clock.tick_action(1.0)
        if player.hp < hp or state.in_combat:
            break
        unfinished.craft_progress += 1
        progressed += 1
    return progressed


def start_make(state, player, output_name: str, tool_name: str, pendulums: int, *, faces=None, selected=None) -> CraftOutcome:
    recipe = make_recipe_by_output(output_name)
    if recipe.id not in player.known_recipes:
        raise ValueError("未知制作表")
    need = effective_required(recipe, tool_name)
    for name, qty in need.items():
        if count_named(player, name) < qty:
            raise ValueError(f"材料不足: {name}")
    required = time_for_tool(recipe, tool_name)
    _require_make_ticks(state, player, pendulums, required)
    consume_named(player, need)
    unfinished = _unfinished_item(recipe, tool_name, required)
    grant_item(player, unfinished, state)
    return continue_make(state, player, unfinished, pendulums, faces=faces, selected=selected)


def continue_make(state, player, unfinished, pendulums: int, *, faces=None, selected=None) -> CraftOutcome:
    remaining = unfinished.craft_required - unfinished.craft_progress
    _require_make_ticks(state, player, pendulums, remaining)
    _advance_unfinished(state, player, unfinished, pendulums)
    if unfinished.craft_progress < unfinished.craft_required:
        return CraftOutcome(unfinished=unfinished, recipe_id=unfinished.recipe_id, tool_name=unfinished.craft_tool)
    recipe = recipe_by_id(unfinished.recipe_id)
    outcome = resolve_check(player, recipe, unfinished.craft_tool, faces=faces, selected=selected)
    if outcome.needs_select:
        outcome.unfinished = unfinished
        return outcome
    player.inventory = [
        item for item in player.inventory if item is not unfinished
    ]
    return complete_recipe(player, recipe, unfinished.craft_tool, faces=faces, selected=selected, state=state)


def finish_from_materials(state, player, kind: str, selected: dict[str, int], tool_name: str, *, faces=None, face_index=None) -> CraftOutcome:
    recipe = match_from_materials(kind, selected, tool_name)
    consume = {
        name: selected[name]
        for name in recipe.required
        if selected.get(name, 0) > 0
    }
    spend_pendulums(state, player, recipe.time_pendulums)
    consume_named(player, consume)
    return complete_recipe(player, recipe, tool_name, faces=faces, selected=face_index, state=state)


def pick_bush(rng=None) -> list:
    import random
    rng = rng or random
    berry = load_item("浆果")
    if berry is None:
        raise ValueError("缺少物品: 浆果")
    berry.count = rng.randint(2, 5)
    if berry.weight:
        berry.weight = berry.weight * berry.count
    items = [berry]
    if rng.random() < 0.1:
        herb = load_item("春之草")
        if herb is None:
            raise ValueError("缺少物品: 春之草")
        items.append(herb)
    return items
