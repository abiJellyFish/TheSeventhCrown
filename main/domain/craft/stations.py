"""场景工具：3×3 燃烧格为火堆；背包工具按名称列出。"""
from domain.craft.recipe import FIRE, HANDS


def detect_named(name: str, state, pos, radius: int = 1) -> bool:
    """扫自身+相邻格。火堆=燃烧格，不写篝火特例。"""
    if name != FIRE:
        return False
    pc, pr = pos[:2]
    for dc in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            if state.is_burning((pc + dc, pr + dr)):
                return True
    return False


def available_tools(state, pos, backpack_names: tuple[str, ...] = ()) -> list[str]:
    tools = [HANDS]
    if detect_named(FIRE, state, pos):
        tools.append(FIRE)
    player = state.controlled_entity
    if player is None:
        return tools
    held = {item.name for item in player.inventory}
    for name in backpack_names:
        if name in held:
            tools.append(name)
    return tools
