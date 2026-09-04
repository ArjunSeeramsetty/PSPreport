"""96-block (15-minute) schedule calendar with an explicit 288-block opt-in."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_BLOCK_COUNT = 96
DEFAULT_BLOCK_MINUTES = 15
FIVE_MINUTE_BLOCK_COUNT = 288
FIVE_MINUTE_BLOCK_MINUTES = 5


@dataclass(frozen=True)
class ScheduleBlock:
    """One IEGC time block on an IST operating day."""

    block_no: int
    start_clock: str
    valid_from: datetime
    valid_to: datetime
    minutes: int


def block_count_for_minutes(minutes: int) -> int:
    """Return the number of blocks in a 24-hour operating day."""

    if minutes not in {DEFAULT_BLOCK_MINUTES, FIVE_MINUTE_BLOCK_MINUTES}:
        raise ValueError(f"Unsupported block duration: {minutes} minutes")
    return (24 * 60) // minutes


def iter_schedule_blocks(
    schedule_date: date,
    *,
    block_count: int = DEFAULT_BLOCK_COUNT,
    minutes: int = DEFAULT_BLOCK_MINUTES,
) -> tuple[ScheduleBlock, ...]:
    """Return validated IST blocks for one operating day."""

    expected = block_count_for_minutes(minutes)
    if block_count != expected:
        raise ValueError(
            f"block_count={block_count} is inconsistent with {minutes}-minute blocks "
            f"(expected {expected})"
        )
    blocks: list[ScheduleBlock] = []
    cursor = datetime.combine(schedule_date, time.min, tzinfo=IST)
    for block_no in range(1, block_count + 1):
        end = cursor + timedelta(minutes=minutes)
        blocks.append(
            ScheduleBlock(
                block_no=block_no,
                start_clock=cursor.strftime("%H:%M"),
                valid_from=cursor,
                valid_to=end,
                minutes=minutes,
            )
        )
        cursor = end
    return tuple(blocks)


def require_standard_blocks(*, block_count: int, minutes: int, allow_five_minute: bool) -> None:
    """Reject 5-minute/288-block grain unless it is explicitly enabled."""

    if block_count == DEFAULT_BLOCK_COUNT and minutes == DEFAULT_BLOCK_MINUTES:
        return
    if (
        allow_five_minute
        and block_count == FIVE_MINUTE_BLOCK_COUNT
        and minutes == FIVE_MINUTE_BLOCK_MINUTES
    ):
        return
    raise ValueError(
        "WBES pipeline models 96 15-minute blocks unless WBES_ALLOW_FIVE_MINUTE=true"
    )


def validate_value_vector(values: list[float], *, block_count: int) -> None:
    """Require one numeric MW value per time block."""

    if len(values) != block_count:
        raise ValueError(f"expected {block_count} block values, found {len(values)}")
