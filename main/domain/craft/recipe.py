"""配方表：加载 JSON，材料包含匹配，复杂盖过简单。"""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from domain.ports import get_repository


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str = ""
    time_factor: float = 1.0
    material_minus: int = 0


@dataclass(frozen=True)
class Recipe:
    id: str
    craft: str
    required: Mapping[str, int]
    output: tuple[str, int]
    time_pendulums: int
    tools: tuple[ToolSpec, ...]
    require_tool: bool
    discovery_needed: int
    complexity: int


HANDS = "徒手"
FIRE = "火堆"

RECIPES: tuple[Recipe, ...] = ()
BY_CRAFT: dict[str, tuple[Recipe, ...]] = {}
BY_OUTPUT_MAKE: dict[str, Recipe] = {}
COOK_INGREDIENTS: set[str] = set()
ALCH_INGREDIENTS: set[str] = set()
MAKE_INGREDIENTS: set[str] = set()


def _parse_recipe(data: dict) -> Recipe:
    required = {str(k): int(v) for k, v in data["required"].items()}
    output = data["output"]
    tools = tuple(
        ToolSpec(
            name=spec["name"],
            category=spec.get("category", ""),
            time_factor=float(spec.get("time_factor", 1.0)),
            material_minus=int(spec.get("material_minus", 0)),
        )
        for spec in data.get("tools", [])
    )
    return Recipe(
        id=data["id"],
        craft=data["craft"],
        required=required,
        output=(output["name"], int(output.get("count", 1))),
        time_pendulums=int(data["time_pendulums"]),
        tools=tools,
        require_tool=bool(data.get("require_tool", False)),
        discovery_needed=int(data.get("discovery_needed", 1)),
        complexity=int(data.get("complexity", sum(required.values()))),
    )


def load_recipes(repository=None) -> None:
    """从 data/recipes 加载并刷新模块级索引。"""
    global RECIPES, BY_CRAFT, BY_OUTPUT_MAKE
    global COOK_INGREDIENTS, ALCH_INGREDIENTS, MAKE_INGREDIENTS
    if repository is None:
        try:
            repository = get_repository()
            raw = repository.load_all("recipes")
        except RuntimeError:
            raw = _load_from_files()
    else:
        raw = repository.load_all("recipes")
    recipes = tuple(sorted((_parse_recipe(data) for data in raw.values()), key=lambda r: r.id))
    RECIPES = recipes
    by_craft: dict[str, list[Recipe]] = {}
    make_out: dict[str, Recipe] = {}
    for recipe in recipes:
        by_craft.setdefault(recipe.craft, []).append(recipe)
        if recipe.craft == "make":
            make_out[recipe.output[0]] = recipe
    BY_CRAFT = {kind: tuple(items) for kind, items in by_craft.items()}
    BY_OUTPUT_MAKE = make_out
    COOK_INGREDIENTS = {name for r in BY_CRAFT.get("cook", ()) for name in r.required}
    ALCH_INGREDIENTS = {name for r in BY_CRAFT.get("alchemy", ()) for name in r.required}
    MAKE_INGREDIENTS = {name for r in BY_CRAFT.get("make", ()) for name in r.required}


def _load_from_files() -> dict[str, dict]:
    directory = Path(__file__).resolve().parents[2] / "data" / "recipes"
    result = {}
    for path in sorted(directory.glob("*.json")):
        import json
        with path.open("r", encoding="utf-8") as stream:
            result[path.stem] = json.load(stream)
    return result


def effective_required(recipe: Recipe, tool_name: str) -> dict[str, int]:
    minus = 0
    for spec in recipe.tools:
        if spec.name == tool_name:
            minus = spec.material_minus
            break
    return {k: max(1, v - minus) for k, v in recipe.required.items()}


def covers(selected: dict[str, int], need: dict[str, int]) -> bool:
    return all(selected.get(k, 0) >= n for k, n in need.items())


def match_from_materials(kind: str, selected: dict[str, int], tool_name: str) -> Recipe:
    if not RECIPES:
        load_recipes()
    hits = []
    for recipe in BY_CRAFT.get(kind, ()):
        if recipe.require_tool and tool_name not in {t.name for t in recipe.tools}:
            continue
        need = effective_required(recipe, tool_name)
        if covers(selected, need):
            hits.append(recipe)
    if not hits:
        raise ValueError("没有匹配的配方")
    return max(hits, key=lambda r: (r.complexity, r.id))


def make_recipe_by_output(name: str) -> Recipe:
    if not RECIPES:
        load_recipes()
    recipe = BY_OUTPUT_MAKE.get(name)
    if recipe is None:
        raise ValueError(f"没有制作配方: {name}")
    return recipe


def recipe_by_id(recipe_id: str) -> Recipe:
    if not RECIPES:
        load_recipes()
    for recipe in RECIPES:
        if recipe.id == recipe_id:
            return recipe
    raise ValueError(f"未知配方: {recipe_id}")


def is_crafted_output(name: str) -> bool:
    if not RECIPES:
        load_recipes()
    return any(recipe.output[0] == name for recipe in RECIPES)


def time_for_tool(recipe: Recipe, tool_name: str) -> int:
    factor = 1.0
    for spec in recipe.tools:
        if spec.name == tool_name:
            factor = spec.time_factor
            break
    return max(1, int(recipe.time_pendulums * factor))


load_recipes()
