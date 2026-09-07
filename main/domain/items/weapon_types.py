"""武器类型表。各类型挂特性，可扩展；武器通过 properties 声明所属类型。"""

WEAPON_TYPES = {
    "light": {
        "tenacity_mult": 0.5,
    },
    "heavy": {
        "tenacity_mult": 2.0,
    },
}


def weapon_type_names(weapon) -> list[str]:
    props = getattr(weapon, "properties", None) or []
    return [str(prop).split("(", 1)[0] for prop in props]


def weapon_tenacity_mult(weapon) -> float:
    mult = 1.0
    if weapon is None:
        return mult
    for name in weapon_type_names(weapon):
        spec = WEAPON_TYPES.get(name)
        if spec is not None and "tenacity_mult" in spec:
            mult *= spec["tenacity_mult"]
    return mult
