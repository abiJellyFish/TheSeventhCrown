"""多格目标形状 —— 形状解析、光标定位与旋转（瞄准系统基础设施）。

形状由 "WxH" 规格描述（如 "1x3" 表示 1 行 × 3 列）。
坐标体系与网格一致：(col, row)，col 向右、row 向下。
锚格 = 观察光标所在格（形状左上角），旋转圆心 = 形状右上格（col 最大、row 最小）。
"""

from dataclasses import dataclass
from domain.entity.rules import SIZE_RANK, size_rank


@dataclass(frozen=True)
class TargetShape:
    """多格目标形状：相对锚格（光标格）的偏移列表。"""
    offsets: tuple[tuple[int, int], ...] = ((0, 0),)
    pivot: tuple[int, int] | None = None
    base_offsets: tuple[tuple[int, int], ...] | None = None
    rotation_steps: int = 0

    @property
    def is_single(self) -> bool:
        return len(self.offsets) <= 1


def entity_reach(entity) -> int:
    """返回实体的固有触及范围；未指定时按体型提供默认值。"""
    explicit = getattr(entity, "reach", None)
    if explicit is not None:
        return max(0, int(explicit))
    return 2 if size_rank(getattr(entity, "size", "medium")) > SIZE_RANK["medium"] else 1


def weapon_melee_reach(weapon, wielder=None) -> int:
    """返回武器近战范围；远程武器也可通过 melee_range 定义近战范围。"""
    if weapon is None:
        return entity_reach(wielder) if wielder is not None else 1
    value = getattr(weapon, "melee_range", None)
    if value is None and getattr(weapon, "melee", None):
        value = weapon.melee.get("melee_range")
    if value is None:
        value = getattr(weapon, "reach", None)
    if value is None:
        value = entity_reach(wielder) if wielder is not None else 1
    return max(0, int(value))


def cells_in_reach(origin: tuple[int, int], reach: int) -> set[tuple[int, int]]:
    """返回以 origin 为中心、按 Chebyshev 距离可触及的格子。"""
    ox, oy = origin
    return {
        (ox + dx, oy + dy)
        for dx in range(-reach, reach + 1)
        for dy in range(-reach, reach + 1)
        if max(abs(dx), abs(dy)) <= reach
    }


def is_in_reach(origin: tuple[int, int], target: tuple[int, int], reach: int) -> bool:
    """判断目标格是否在触及范围内。"""
    return max(abs(target[0] - origin[0]), abs(target[1] - origin[1])) <= reach


def parse_shape(spec: str | None) -> TargetShape:
    """解析形状规格："1x3" → 1 行 3 列（横向一排）；缺省/空/非法 → 单格。"""
    if not spec:
        return TargetShape()
    rows, _, cols = spec.partition("x")
    try:
        row_n = max(1, int(rows))
        col_n = max(1, int(cols))
    except ValueError:
        return TargetShape()
    offsets = tuple((c, r) for r in range(row_n) for c in range(col_n))
    return TargetShape(
        offsets,
        pivot_offset(TargetShape(offsets)),
        base_offsets=offsets,
    )


def shape_from_pending_attack(pending_attack: dict) -> TargetShape:
    """读取瞄准阶段当前形状，优先使用旋转后的偏移。"""
    rotation_steps = pending_attack.get("target_rotation", 0)
    if rotation_steps:
        base = parse_shape(pending_attack.get("target_shape") or "")
        return _shape_at_rotation(base, rotation_steps)
    offsets = pending_attack.get("target_offsets")
    if offsets:
        return TargetShape(tuple(offsets), pivot=(0, 0))
    return parse_shape(pending_attack.get("target_shape") or "")


def pivot_offset(shape: TargetShape) -> tuple[int, int]:
    """旋转圆心（右上格）：col 最大、row 最小的格偏移。"""
    return (max(c for c, _ in shape.offsets), min(r for _, r in shape.offsets))


def rotate_shape(shape: TargetShape) -> tuple[TargetShape, tuple[int, int]]:
    """绕形状中心旋转 45°（屏幕坐标 col 右、row 下）。

    Returns:
        (旋转后形状, 新锚格相对原锚格的偏移)。

    使用网格方向旋转：每个偏移按照其 Chebyshev 距离保持格数，
    因此横向形状会依次经过斜向和纵向，而不会因浮点取整重叠。
    """
    base = shape.base_offsets or shape.offsets
    next_step = (shape.rotation_steps + 1) % 8
    rotated = _shape_at_rotation(
        TargetShape(tuple(base), base_offsets=tuple(base)),
        next_step,
    )
    return rotated, shape.pivot or pivot_offset(shape)


def _shape_at_rotation(shape: TargetShape, steps: int) -> TargetShape:
    """返回离散 45 度方向；偶数方向使用精确 90 度矩形变换。"""
    base = shape.base_offsets or shape.offsets
    steps %= 8
    if steps % 2 == 0:
        offsets = _rotate_quarter_turns(base, steps // 2)
    else:
        offsets = _rotate_diagonal_once(base)
        if steps >= 3:
            offsets = _rotate_quarter_turns(offsets, steps // 2)
    return TargetShape(
        tuple(offsets),
        pivot=(0, 0),
        base_offsets=tuple(base),
        rotation_steps=steps,
    )


def _rotate_quarter_turns(offsets: tuple[tuple[int, int], ...], turns: int) -> tuple[tuple[int, int], ...]:
    result = tuple(offsets)
    for _ in range(turns % 4):
        max_row = max(row for _, row in result)
        result = tuple(
            (max_row - row, col)
            for col, row in result
        )
        min_col = min(col for col, _ in result)
        min_row = min(row for _, row in result)
        result = tuple((col - min_col, row - min_row) for col, row in result)
    return tuple(sorted(result))


def _rotate_diagonal_once(offsets: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """将连续形状离散到一次 45 度方向并保持格子连续。"""
    if len(offsets) > 4:
        row_count = max(2, round(len(offsets) ** 0.5))
        col_count = (len(offsets) + row_count - 1) // row_count
        cells = []
        for row in range(row_count):
            start = row % 2
            for col in range(col_count):
                if len(cells) == len(offsets):
                    break
                cells.append((col + start, row))
        min_col = min(col for col, _ in cells)
        min_row = min(row for _, row in cells)
        return tuple(sorted((col - min_col, row - min_row) for col, row in cells))

    source = TargetShape(tuple(offsets), pivot=pivot_offset(TargetShape(tuple(offsets))))
    px, py = source.pivot or pivot_offset(source)
    rotated = []
    for ox, oy in source.offsets:
        dx, dy = ox - px, oy - py
        distance = max(abs(dx), abs(dy))
        if distance == 0:
            rotated.append((0, 0))
            continue
        direction = (0, 0)
        if dx < 0 and dy == 0:
            direction = (-1, 1)
        elif dx < 0 and dy > 0:
            direction = (0, 1)
        elif dx == 0 and dy > 0:
            direction = (1, 1)
        elif dx > 0 and dy > 0:
            direction = (1, 0)
        elif dx > 0 and dy == 0:
            direction = (1, -1)
        elif dx > 0 and dy < 0:
            direction = (0, -1)
        elif dx == 0 and dy < 0:
            direction = (-1, -1)
        else:
            direction = (0, -1)
        rotated.append((direction[0] * distance, direction[1] * distance))
    unique = set(rotated)
    if len(unique) == len(rotated):
        return tuple(sorted(unique))
    return tuple(sorted(_fill_connected_cells(unique, len(rotated))))


def _fill_connected_cells(
    cells: set[tuple[int, int]],
    target_count: int,
) -> set[tuple[int, int]]:
    """用相邻格补齐离散旋转中的碰撞，不改变形状格子总数。"""
    result = set(cells)
    frontier = set(cells)
    while len(result) < target_count:
        candidates = {
            (col + dc, row + dr)
            for col, row in frontier
            for dc, dr in (
                (-1, -1), (-1, 0), (-1, 1), (0, -1),
                (0, 1), (1, -1), (1, 0), (1, 1),
            )
            if (col + dc, row + dr) not in result
        }
        if not candidates:
            break
        chosen = min(candidates, key=lambda pos: (pos[1], pos[0]))
        result.add(chosen)
        frontier.add(chosen)
    return result


def shape_cells(anchor: tuple[int, int], shape: TargetShape) -> list[tuple[int, int]]:
    """锚格 + 偏移 → 绝对坐标列表。"""
    ac, ar = anchor
    return [(ac + c, ar + r) for c, r in shape.offsets]
