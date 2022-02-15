from typing import Any


def full_name(o: Any) -> str:
    return f"{o.__module__}.{o.__class__.__qualname__}"
