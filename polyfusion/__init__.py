"""PolyFusion: modular Python port of the ENN tokamak 0-D system code.

Public API:
    funsc(...)        -> Result   single-point 0-D power balance
    Result                        dataclass of outputs
    reactivity(T, ic) -> float    Maxwellian <sigma*v>(T)
"""

# Cap BLAS threads BEFORE numpy is imported by any submodule.  On this Windows
# numpy build the threaded OpenBLAS path is pathologically slow for medium
# matrices (a 121x121 solve ~0.6 s threaded vs ~0.4 ms single-threaded); the
# matrices here are tiny so single-threaded is strictly faster and identical.
# setdefault respects an explicit user override.  (Entry points that import
# numpy before polyfusion should set these themselves — e.g. app/server.py does.)
import os as _os
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    _os.environ.setdefault(_v, "1")

from .tokamak import funsc, Result
from .reactivity import reactivity

__all__ = ["funsc", "Result", "reactivity"]
__version__ = "0.1.0"
