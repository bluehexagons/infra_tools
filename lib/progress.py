"""Progress tracking for remote setup steps."""

from __future__ import annotations
import sys
from typing import Callable, Any

_steps: list[tuple[str, Callable[..., Any]]] = []
_current_step: int = 0
_total_steps: int = 0


def register_step(name: str, func: Callable[..., Any]) -> None:
    global _steps
    _steps.append((name, func))


def get_total_steps() -> int:
    return len(_steps)


def progress_bar(current: int, total: int, width: int = 20) -> str:
    filled = int(width * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    percent = int(100 * current / total) if total > 0 else 0
    return f"[{bar}] {percent}%"


def run_step(step_num: int, name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    total = get_total_steps()
    bar = progress_bar(step_num, total)
    print(f"\n{bar} [{step_num}/{total}] {name}")
    sys.stdout.flush()
    result = func(*args, **kwargs)
    return result


def run_all_steps(*args: Any, **kwargs: Any) -> None:
    global _current_step
    total = get_total_steps()
    for i, (name, func) in enumerate(_steps, 1):
        _current_step = i
        run_step(i, name, func, *args, **kwargs)
    
    bar = progress_bar(total, total)
    print(f"\n{bar} All steps completed!")
    sys.stdout.flush()


def clear_steps() -> None:
    global _steps, _current_step
    _steps = []
    _current_step = 0
