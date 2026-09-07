"""历法 —— 由钟摆推导日名、月名、纪年、日时段与天光。"""

from enum import Enum

from domain.fov import LightLevel

PENDULUMS_PER_DAY = 5000
PENDULUMS_PER_MONTH = 50000
PENDULUMS_PER_YEAR = 250000
PENDULUMS_PER_PERIOD = 1000


class WeekDay(Enum):
    DIVINE_WORD = "神言日"
    BLACK_CAT = "黑猫日"
    RAVEN = "鸦之日"
    MIRROR = "镜面日"
    RADIANCE = "光耀日"
    NEW_LEAF = "新叶日"
    SEA = "海之日"
    DREAM = "幻梦日"
    RAINBOW = "虹光日"
    WISH = "祈愿日"


class Month(Enum):
    ICE_WATER = "冰水月"
    STARS = "繁星月"
    SPIRIT_FEATHER = "灵羽月"
    TRAVELER = "旅者月"
    CORNER = "角落月"


class TimeOfDay(Enum):
    DAWN = "初晨"
    NOON = "午间"
    DUSK = "日落"
    NIGHT = "夜幕"


_WEEK_DAYS = tuple(WeekDay)
_MONTHS = tuple(Month)
_TIME_SLOTS = (
    TimeOfDay.NIGHT,
    TimeOfDay.DAWN,
    TimeOfDay.NOON,
    TimeOfDay.DUSK,
    TimeOfDay.NIGHT,
)


def _require_pendulum(pendulum_count: int) -> int:
    if pendulum_count < 0:
        raise ValueError("pendulum_count 不能为负")
    return pendulum_count


def week_day(pendulum_count: int) -> WeekDay:
    pendulum_count = _require_pendulum(pendulum_count)
    return _WEEK_DAYS[(pendulum_count // PENDULUMS_PER_DAY) % len(_WEEK_DAYS)]


def month(pendulum_count: int) -> Month:
    pendulum_count = _require_pendulum(pendulum_count)
    return _MONTHS[(pendulum_count // PENDULUMS_PER_MONTH) % len(_MONTHS)]


def era_year(pendulum_count: int) -> int:
    pendulum_count = _require_pendulum(pendulum_count)
    return pendulum_count // PENDULUMS_PER_YEAR + 1


def time_of_day(pendulum_count: int) -> TimeOfDay:
    pendulum_count = _require_pendulum(pendulum_count)
    return _TIME_SLOTS[(pendulum_count % PENDULUMS_PER_DAY) // PENDULUMS_PER_PERIOD]


def sky_light(pendulum_count: int) -> LightLevel:
    if time_of_day(pendulum_count) is TimeOfDay.NIGHT:
        return LightLevel.DIM
    return LightLevel.BRIGHT


def format_clock_right(pendulum_count: int) -> str:
    pendulum_count = _require_pendulum(pendulum_count)
    tod = time_of_day(pendulum_count).value
    within_day = pendulum_count % PENDULUMS_PER_DAY
    return (
        f"钟摆{within_day} {tod} {week_day(pendulum_count).value} "
        f"{month(pendulum_count).value} 纪年{era_year(pendulum_count)}"
    )
