"""物品品质：七档倍率、用时缩放、检定查表。"""

QUALITIES: tuple[str, ...] = (
    "破损", "粗劣", "普通", "精良", "极佳", "大师", "传奇",
)

QUALITY_MULT: dict[str, float] = {
    "破损": 0.20,
    "粗劣": 0.50,
    "普通": 1.00,
    "精良": 1.10,
    "极佳": 1.20,
    "大师": 1.50,
    "传奇": 2.25,
}

_QUALITY_INDEX: dict[str, int] = {name: i for i, name in enumerate(QUALITIES)}

_QUALITY_BY_TOTAL: tuple[tuple[int, str], ...] = (
    (4, "破损"),
    (14, "粗劣"),
    (19, "普通"),
    (24, "精良"),
    (29, "极佳"),
    (39, "大师"),
)


def require_quality(quality: str) -> str:
    """非法品质抛错。"""
    if quality not in QUALITY_MULT:
        raise ValueError(f"非法品质: {quality}")
    return quality


def scale_value(base: int | float, quality: str) -> int:
    """使用时 round(基值 × 倍率)。"""
    return round(float(base) * QUALITY_MULT[require_quality(quality)])


def quality_from_total(total: int) -> str:
    """用总点数查品质表。"""
    for cap, name in _QUALITY_BY_TOTAL:
        if total <= cap:
            return name
    return "传奇"


def shift_quality(quality: str, delta: int) -> str:
    """品质升降档，夹在破损–传奇。"""
    idx = _QUALITY_INDEX[require_quality(quality)] + delta
    return QUALITIES[max(0, min(len(QUALITIES) - 1, idx))]
