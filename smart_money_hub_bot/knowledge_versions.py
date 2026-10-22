"""Version-number rules for administrator-approved knowledge entries."""

from typing import Any


def next_version_number(versions: list[dict[str, Any]]) -> int:
    return max((int(version.get("version", 0)) for version in versions), default=0) + 1
