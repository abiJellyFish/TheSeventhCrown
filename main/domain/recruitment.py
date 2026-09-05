"""盟友招募规则。"""

from dataclasses import dataclass

from domain.dice import roll_d20, check_total
from domain.entity import Entity
from domain.faction import get_attitude


@dataclass(frozen=True)
class RecruitmentResult:
    success: bool
    player_roll: int
    target_roll: int
    message: str


def attempt_recruit(state, target: Entity, *, attitude: str | None = None,
                    cost: int = 0) -> RecruitmentResult:
    """执行双方 d20+魅力调整值比较，并在成功后加入队伍。"""
    player = state.controlled_entity
    if player is None:
        raise ValueError("没有受控角色")
    if target.body_type == "beast":
        return RecruitmentResult(False, 0, 0, "野兽不能招募")
    target_attitude = attitude or get_attitude(target, player)
    if target_attitude not in ("友好", "冷漠"):
        return RecruitmentResult(False, 0, 0, "目标态度不适合招募")
    if len(state.party) >= state.max_party_size:
        return RecruitmentResult(False, 0, 0, "队伍已满")
    player_roll = check_total(
        player, roll_d20(advantage=1 if target_attitude == "友好" else 0),
        player.stat_adjust("cha")
    )
    target_roll = check_total(target, roll_d20(), target.stat_adjust("cha"))
    if player_roll <= target_roll:
        return RecruitmentResult(False, player_roll, target_roll, "魅力检定失败")
    if player.gp < cost:
        return RecruitmentResult(False, player_roll, target_roll, "金币不足")
    if cost:
        player.gp -= cost
    state.add_party_member(target)
    return RecruitmentResult(True, player_roll, target_roll, "招募成功")
