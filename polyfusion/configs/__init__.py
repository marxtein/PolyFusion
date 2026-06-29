"""Per-configuration 0-D models + the config-agnostic registry.

Tokamak lives in ``polyfusion.tokamak`` (the original PolyFusion).  Additional
magnetic configurations live here.  :mod:`base` exposes them through a uniform
:class:`ConfigSpec` registry so front-ends and the scanner are config-agnostic.
"""

from .mirror import solve_mirror, MirrorResult
from .frc import solve_frc, FRCResult
from .dipole import solve_dipole, DipoleResult
from .stellarator import solve_stellarator, StellaratorResult
from .base import ConfigSpec, REGISTRY, get, TOKAMAK, MIRROR, FRC, DIPOLE, STELLARATOR

__all__ = [
    "solve_mirror",
    "MirrorResult",
    "solve_frc",
    "FRCResult",
    "solve_dipole",
    "DipoleResult",
    "solve_stellarator",
    "StellaratorResult",
    "ConfigSpec",
    "REGISTRY",
    "get",
    "TOKAMAK",
    "MIRROR",
    "FRC",
    "DIPOLE",
    "STELLARATOR",
]
