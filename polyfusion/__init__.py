"""PolyFusion: modular Python port of the ENN tokamak 0-D system code.

Public API:
    funsc(...)        -> Result   single-point 0-D power balance
    Result                        dataclass of outputs
    reactivity(T, ic) -> float    Maxwellian <sigma*v>(T)
"""

from .tokamak import funsc, Result
from .reactivity import reactivity

__all__ = ["funsc", "Result", "reactivity"]
__version__ = "0.1.0"
