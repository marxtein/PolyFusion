"""Abstract mirror geometry interface."""

from abc import ABC, abstractmethod

_REGISTRY: dict[str, type] = {}


def register_geometry(name: str, cls: type) -> None:
    """Register a concrete MirrorGeometry subclass."""
    _REGISTRY[name] = cls


def get_geometry(name: str) -> type:
    """Look up a concrete MirrorGeometry class by name."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"Unknown geometry '{name}'. Available: {available}") from None


class MirrorGeometry(ABC):
    """Abstract base for mirror plasma geometry.

    Concrete subclasses compute the on-axis magnetic field :math:`B(z)`,
    the plasma radius :math:`a(z)` via flux conservation, and derived
    global quantities (volumes, areas) in ``__init__`` so that the
    property-like abstract methods below are cheap lookups.
    """

    @abstractmethod
    def volume(self) -> float:
        """Total plasma volume :math:`V_p` [m³]."""
        ...

    @abstractmethod
    def surface(self) -> float:
        """Plasma side surface area [m²]."""
        ...

    @abstractmethod
    def wall_surface(self) -> float:
        """First-wall surface area [m²]."""
        ...

    @abstractmethod
    def throat_area(self) -> float:
        """Single throat magnetic flux area [m²].

        The total throat area through *both* ends is ``2 * throat_area()``.
        """
        ...

    @abstractmethod
    def throat_radius(self) -> float:
        """Plasma radius at the mirror throat [m]."""
        ...

    @abstractmethod
    def B(self, z: float) -> float:
        """On-axis magnetic field at axial position *z* [T].

        *z* = 0 corresponds to the central-cell midplane.
        """
        ...

    @abstractmethod
    def a(self, z: float) -> float:
        """Plasma radius at axial position *z* [m].

        Computed from flux conservation: :math:`a(z) = a_c \\sqrt{B_c / B(z)}`.
        """
        ...

    @abstractmethod
    def profile_at(self, z: float) -> dict:
        """Convenience: return ``{B, a, dB_dz, da_dz}`` at axial position *z*."""
        ...
