"""领域级濒死与死亡豁免系统。"""

from domain.dice import roll_d20


DEATH_SAVE_INTERVAL = 6.0


class DeathSaves:
    """管理单个实体的死亡豁免状态。"""

    def __init__(self):
        self.successes = 0
        self.failures = 0
        self.death_injury = 0
        self.max_hp = 30

    @property
    def is_stable(self) -> bool:
        return self.successes >= 3

    @property
    def is_dead(self) -> bool:
        return self.failures >= 3 or self.death_injury >= self.max_hp

    def reset(self) -> None:
        self.successes = 0
        self.failures = 0
        self.death_injury = 0

    def take_damage_at_zero(self, damage: int, max_hp: int,
                            critical: bool = False) -> None:
        self.max_hp = max_hp
        self.death_injury += damage
        self.failures += 2 if critical else 1

    def roll_save(self) -> str:
        roll = roll_d20()
        if roll == 1:
            self.failures += 2
            return "crit_fail"
        if roll == 20:
            return "crit_success"
        if roll >= 10:
            self.successes += 1
            return "success"
        self.failures += 1
        return "failure"


class DeathSystem:
    """驱动所有实体的独立死亡豁免计时。"""

    def __init__(self, state=None):
        self.state = state

    def bind(self, state) -> None:
        self.state = state

    def on_enter_dying(self, creature) -> None:
        creature._death_save_pendulums = 0.0
        self._log(f"{creature.name}进入濒死，6个钟摆后进行死亡豁免")

    def advance(self, delta: float) -> None:
        if delta < 0:
            raise ValueError("death save time delta must be non-negative")
        for creature in self._entities():
            if not creature.has_status("濒死"):
                continue
            creature._death_save_pendulums += delta
            while creature._death_save_pendulums >= DEATH_SAVE_INTERVAL:
                creature._death_save_pendulums -= DEATH_SAVE_INTERVAL
                self.roll(creature)

    def stabilize(self, creature) -> None:
        creature.hp = 1
        creature.add_status("昏迷")
        if creature.death_saves:
            creature.death_saves.reset()

    def roll(self, creature) -> str:
        result = creature._get_death_saves().roll_save()
        if result == "crit_success":
            creature.hp = 1
            self._log(f"{creature.name} 挺了过来，恢复了意识")
            return "woke"
        if creature.death_saves.is_dead:
            creature._die()
            return "died"
        if creature.death_saves.is_stable:
            self.stabilize(creature)
            self._log(f"{creature.name} 稳定下来，陷入昏迷")
            return "stable"
        labels = {
            "crit_fail": "大失败",
            "failure": "失败",
            "success": "成功",
        }
        self._log(
            f"{creature.name} 的死亡豁免{labels[result]}"
            f"（{creature.death_saves.failures}失败/"
            f"{creature.death_saves.successes}成功）"
        )
        return "ongoing"

    def _entities(self):
        if self.state is None:
            return ()
        return (creature for creature, _ in self.state.entities)

    def _log(self, message: str) -> None:
        if self.state is not None:
            self.state.emit_log(message)
