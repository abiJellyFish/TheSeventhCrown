"""种植系统 —— 作物状态、播种、每日生长、收获。"""

import random
from dataclasses import dataclass

from domain.movement import Terrain
from domain.ports import get_repository
from domain.element import WET_DURATION


_TERRAIN_BY_NAME = {
    "plain": Terrain.PLAIN,
    "grass": Terrain.GRASS,
    "floor": Terrain.FLOOR,
}


@dataclass
class CropPlot:
    """单格作物状态。"""

    seed_name: str
    growth_stage: int = 0
    water_storage: int = 0
    wither_count: int = 0
    withered: bool = False


def load_seed_config(seed_name: str) -> dict | None:
    """从物品数据读取种子配置（crop 字段）。"""
    data = get_repository().load_item_data(seed_name)
    if not data:
        return None
    crop = data.get("crop")
    return crop if isinstance(crop, dict) else None


def _terrain_ok(terrain: Terrain, suitable: list[str]) -> bool:
    allowed = {_TERRAIN_BY_NAME.get(t, t) for t in suitable}
    return terrain in allowed


def can_plant_at(state, pos: tuple[int, int], seed_name: str) -> bool:
    """目标格是否可播种。"""
    if pos in state.crops:
        return False
    if state.get_entity_at(pos[0], pos[1]):
        return False
    cfg = load_seed_config(seed_name)
    if not cfg:
        return False
    terrain = state.map[pos]
    if not _terrain_ok(terrain, cfg.get("suitable_terrain", [])):
        return False
    return True


def plant_seed(state, pos: tuple[int, int], seed_name: str) -> bool:
    """在目标格播种（消耗由调用方处理）。"""
    if not can_plant_at(state, pos, seed_name):
        return False
    state.crops[pos] = CropPlot(seed_name=seed_name)
    return True


def add_crop_water(state, pos: tuple[int, int], amount: int = 1) -> None:
    """潮湿传导：为格上作物增加储水（由 apply_wet_to_tile 间接调用）。"""
    plot = state.crops.get(pos)
    if plot is None or plot.withered:
        return
    plot.water_storage += amount


def sync_crop_water_from_wet(state, pos: tuple[int, int]) -> None:
    """格面潮湿时，传导储水至该格作物。"""
    if pos not in state.wet_surfaces:
        return
    add_crop_water(state, pos, 1)


def apply_wet_to_tile(state, pos: tuple[int, int]) -> None:
    """为格子附加潮湿；作物储水由潮湿传导，不直接写入。"""
    state.wet_surfaces[pos] = WET_DURATION
    sync_crop_water_from_wet(state, pos)


def is_crop_mature(plot: CropPlot, cfg: dict) -> bool:
    return not plot.withered and plot.growth_stage >= cfg.get("growth_days", 1)


def harvest_crop(state, pos: tuple[int, int]) -> list[dict]:
    """收获成熟作物，返回物品 ref 列表并清除植株。"""
    plot = state.crops.get(pos)
    if plot is None or plot.withered:
        return []
    cfg = load_seed_config(plot.seed_name)
    if not cfg or not is_crop_mature(plot, cfg):
        return []
    refs: list[dict] = []
    if plot.wither_count <= 0:
        cherry_count = 2 + random.randint(1, 2)
        refs.append({"name": cfg.get("harvest_item", "樱桃"), "count": cherry_count})
        if random.randint(0, 1) == 1:
            refs.append({"name": plot.seed_name, "count": 1})
    else:
        refs.append({"name": cfg.get("harvest_item", "樱桃"), "count": random.randint(1, 2)})
    del state.crops[pos]
    return refs


def pick_crop(state, pos: tuple[int, int]) -> bool:
    """未成熟采摘：植株消失，通常无收获。"""
    if pos not in state.crops:
        return False
    del state.crops[pos]
    return True


def clear_withered_crop(state, pos: tuple[int, int]) -> bool:
    """清除枯萎植株。"""
    plot = state.crops.get(pos)
    if plot is None or not plot.withered:
        return False
    del state.crops[pos]
    return True


def tick_daily_crops(state) -> list[str]:
    """每天结束时推进所有作物生长/枯萎。"""
    logs: list[str] = []
    for pos, plot in list(state.crops.items()):
        if plot.withered:
            continue
        cfg = load_seed_config(plot.seed_name)
        if not cfg:
            continue
        growth_days = cfg.get("growth_days", 1)
        if plot.growth_stage >= growth_days:
            continue
        water_need = cfg.get("water_need", 1)
        wither_limit = cfg.get("wither_limit", 5)
        if plot.water_storage >= water_need:
            plot.water_storage = 0
            plot.growth_stage += 1
        else:
            plot.water_storage = 0
            plot.wither_count += 1
        if plot.wither_count >= wither_limit:
            plot.withered = True
            logs.append(f"({pos[0]},{pos[1]}) 的作物枯萎了")
    return logs


def crop_map_render(plot: CropPlot) -> tuple[str, str]:
    """地图渲染：逗号；未浇水浅粉、已储水深红、成熟红色分号、枯萎暗绿。"""
    if plot.withered:
        return ",", "#225222"
    cfg = load_seed_config(plot.seed_name) or {}
    if is_crop_mature(plot, cfg):
        return cfg.get("mature_char", ";"), cfg.get("mature_color", "#FF3333")
    if plot.water_storage > 0:
        return ",", "#FF3333"
    return ",", "#ff9ac1"


def crop_label(state, pos: tuple[int, int]) -> str:
    """观察/交互用作物描述。"""
    plot = state.crops.get(pos)
    if plot is None:
        return ""
    cfg = load_seed_config(plot.seed_name) or {}
    harvest_name = cfg.get("harvest_item", "作物")
    if plot.withered:
        return f"枯萎的{harvest_name}植株"
    days = cfg.get("growth_days", 1)
    return f"{harvest_name}植株  生长{plot.growth_stage}/{days}  枯萎{plot.wither_count}/{cfg.get('wither_limit', 5)}"
