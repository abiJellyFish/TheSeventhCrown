"""隐匿领域状态容器。"""

from dataclasses import dataclass, field


@dataclass
class StealthState:
    hidden_from: dict[int, set[int]] = field(default_factory=dict)
    spot_clock: dict[tuple[int, int], int] = field(default_factory=dict)
    seen_snap: dict[int, set[int]] = field(default_factory=dict)
    spot_memo: dict[tuple[int, int], bool] = field(default_factory=dict)

    def remove_entity(self, entity_id: int) -> None:
        self.hidden_from.pop(entity_id, None)
        for observers in self.hidden_from.values():
            observers.discard(entity_id)
        self.seen_snap.pop(entity_id, None)
        for key in tuple(self.spot_clock):
            if entity_id in key:
                del self.spot_clock[key]
