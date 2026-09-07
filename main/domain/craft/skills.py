"""烹饪 / 制作 / 炼药：经验、优势骰、所选面值 → 品质。"""
from domain.classes import expertise_level, proficiency_level
from domain.craft.quality import quality_from_total, shift_quality
from domain.dice import roll_adv_dice


def grant_craft_exp(entity, kind: str, amount: float = 0.1) -> None:
    """完成一次制作/烹饪/炼药：经验 +0.1。"""
    if not kind:
        raise ValueError("craft kind 不能为空")
    entity.craft_experience[kind] = entity.craft_experience.get(kind, 0.0) + amount


def grant_tool_exp(entity, category: str, amount: float = 0.1) -> None:
    """使用工具并完成一次：工具熟练经验 +0.1。"""
    if category:
        entity.tool_experience[category] = (
            entity.tool_experience.get(category, 0.0) + amount
        )


def craft_level(entity, kind: str) -> int:
    """等级 = floor(exp)，调整值 = 等级。"""
    return int(entity.craft_experience.get(kind, 0.0))


def tool_proficiency_level(entity, category: str) -> int:
    return proficiency_level(entity.tool_experience.get(category, 0.0))


def tool_expertise_level(entity, category: str) -> int:
    return expertise_level(entity.tool_experience.get(category, 0.0))


def roll_faces(advantage: int = 0) -> list[int]:
    """调用现有优势骰；advantage=0 返回 1 颗。"""
    return roll_adv_dice(advantage=advantage)


def quality_from_face(face: int, level: int, *, halve: bool = False) -> str:
    """总点数 = 面值 + 等级；炼药未学会则 //2 再查表；面值 1/20 品质±1 档。"""
    total = face + level
    if halve:
        total //= 2
    quality = quality_from_total(total)
    if face == 1:
        return shift_quality(quality, -1)
    if face == 20:
        return shift_quality(quality, 1)
    return quality
