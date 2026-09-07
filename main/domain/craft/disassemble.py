"""拆解成品或未完成物：默认 1 钟摆，原料减半最少 1。"""
from domain.craft.engine import spend_pendulums
from domain.craft.recipe import RECIPES, load_recipes, recipe_by_id
from domain.loot import grant_item
from domain.trade import load_item


def recipe_for_output(name: str):
    if not RECIPES:
        load_recipes()
    for recipe in RECIPES:
        if recipe.output[0] == name:
            return recipe
    return None


def can_disassemble(item) -> bool:
    if getattr(item, "unfinished", False) and item.recipe_id:
        return True
    return recipe_for_output(item.name) is not None


def disassemble(state, player, item) -> list:
    if getattr(item, "unfinished", False):
        recipe = recipe_by_id(item.recipe_id)
    else:
        recipe = recipe_for_output(item.name)
        if recipe is None:
            raise ValueError(f"不能拆解: {item.name}")
    spend_pendulums(state, player, 1)
    if item.count > 1:
        unit = item.weight / item.count
        item.count -= 1
        item.weight -= unit
    else:
        player.inventory.remove(item)
    produced = []
    for name, qty in recipe.required.items():
        got = max(1, qty // 2)
        material = load_item(name)
        if material is None:
            raise ValueError(f"缺少物品: {name}")
        material.count = got
        if material.weight:
            material.weight = material.weight * got
        grant_item(player, material, state)
        produced.append(material)
    return produced
