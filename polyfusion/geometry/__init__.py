"""Mirror geometry modules — abstract interface + concrete implementations."""

from .base import MirrorGeometry, get_geometry
from .sin2_simple import Sin2SimpleGeometry  # noqa: F401 — triggers register_geometry
from .multi_zone import MultiZoneGeometry  # noqa: F401 — triggers register_geometry

__all__ = ["MirrorGeometry", "get_geometry", "Sin2SimpleGeometry", "MultiZoneGeometry"]
