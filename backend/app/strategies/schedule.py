"""Calendar schedules, evaluated on closed bars; executions occur at next open."""
import pandas as pd

def contribution_schedule(index: pd.DatetimeIndex, every: int, unit: str, delay: int = 0) -> list[bool]:
    if every < 1 or delay < 0 or unit not in {"hours", "days", "weeks", "months"}:
        raise ValueError("定投间隔必须为正数，延迟不能为负，单位必须有效")
    result = [False] * len(index)
    if delay >= len(index):
        return result
    offset = {"hours": pd.DateOffset(hours=every), "days": pd.DateOffset(days=every),
              "weeks": pd.DateOffset(weeks=every), "months": pd.DateOffset(months=every)}[unit]
    anchor = index[delay]
    next_due = anchor
    count = 0
    for i in range(delay, len(index)):
        if index[i] >= next_due:
            result[i] = True
            # Coalesce missed dates into one contribution; do not manufacture
            # multiple historical fills on a single coarse bar.
            while next_due <= index[i]:
                count += 1
                next_due = anchor + count * offset
    return result
