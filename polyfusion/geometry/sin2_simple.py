"""sin²-throat mirror geometry — extracted from configs/mirror.py lines 229-246.

Cylinder + flux-mapped throat regions with the analytic B(z) profile:
  B(z)/B_c = 1 + (R_mc - 1) sin²(πz / 2L_th)
"""

from __future__ import annotations

import math

import numpy as np

from .base import MirrorGeometry, register_geometry


class Sin2SimpleGeometry(MirrorGeometry):
    """Cylinder + sin² flux-mapped throat mirror geometry.

    Parameters
    ----------
    a_c : float
        Central-cell plasma radius [m].
    L_c : float
        Central-cell length [m].
    B_vac : float
        Vacuum on-axis magnetic field [T].
    R_mirror : float
        Vacuum mirror ratio.
    beta : float
        Peak diamagnetic beta, 0 ≤ beta < 1.
    f_throat : float
        Throat length fraction of L_c (default 0.1).
    g : float
        Gap between plasma and first wall [m] (default 0.0).
    """

    def __init__(
        self,
        a_c: float,
        L_c: float,
        B_vac: float,
        R_mirror: float,
        beta: float,
        f_throat: float = 0.1,
        g: float = 0.0,
    ) -> None:
        R_mc = R_mirror / math.sqrt(1 - beta)
        B_c = B_vac * math.sqrt(1 - beta)
        L_th = f_throat * L_c

        self._a_c = a_c
        self._L_c = L_c
        self._B_c = B_c
        self._R_mc = R_mc
        self._L_th = L_th
        self._g = g
        self._beta = beta
        self._R_mirror = R_mirror

        # ---------- geometry: cylinder + flux-mapped throat regions ----------
        # (mirror.py lines 229-246, exact reproduction)
        V_cyl = math.pi * a_c**2 * L_c
        V_end = (
            2 * math.pi * a_c**2 * L_th / math.sqrt(R_mc) if L_th > 0 else 0.0
        )
        self._Vp = V_cyl + V_end

        # plasma side surface: cylinder part + throat part (numeric, a(z) flux map)
        if L_th > 0:
            zt = np.linspace(0.0, 1.0, 60)
            a_z = a_c / np.sqrt(
                1 + (R_mc - 1) * np.sin(math.pi * zt / 2) ** 2
            )
            S_end = 2 * 2 * math.pi * float(np.trapezoid(a_z, zt)) * L_th
        else:
            S_end = 0.0
        self._Sp = 2 * math.pi * a_c * L_c + S_end

        r_w = a_c + g
        Sw = 2 * math.pi * r_w * L_c + 2 * math.pi * r_w**2  # side + end plates
        self._Sw = Sw

        A_throat = math.pi * a_c**2 * math.sqrt(1 - beta) / R_mirror
        self._A_throat = A_throat
        self._a_throat = math.sqrt(A_throat / math.pi)

    # -- MirrorGeometry abstract methods (all pre-computed properties) ---------

    def volume(self) -> float:
        """Total plasma volume Vp [m³]."""
        return self._Vp

    def surface(self) -> float:
        """Plasma side surface area [m²]."""
        return self._Sp

    def wall_surface(self) -> float:
        """First-wall surface area [m²]."""
        return self._Sw

    def throat_area(self) -> float:
        """Single throat magnetic flux area [m²]."""
        return self._A_throat

    def throat_radius(self) -> float:
        """Plasma radius at the mirror throat [m]."""
        return self._a_throat

    def B(self, z: float) -> float:
        """On-axis magnetic field at axial position z [T].

        Piecewise model:
        - Central cell (|z| ≤ L_c/2): B = B_c (uniform)
        - Throat (L_c/2 < |z| ≤ L_c/2 + L_th):
          B(z) = B_c * (1 + (R_mc - 1) * sin²(π z_th / 2 L_th))
        - Mirror peak (|z| > L_c/2 + L_th): B = B_c * R_mc
        """
        abs_z = abs(z)
        if abs_z <= self._L_c / 2:
            return self._B_c
        z_th = abs_z - self._L_c / 2
        if z_th <= self._L_th:
            return self._B_c * (
                1 + (self._R_mc - 1) * math.sin(math.pi * z_th / (2 * self._L_th)) ** 2
            )
        return self._B_c * self._R_mc

    def a(self, z: float) -> float:
        """Plasma radius at axial position z [m].

        Flux conservation: a(z) = a_c * sqrt(B_c / B(z)).
        """
        return self._a_c * math.sqrt(self._B_c / self.B(z))

    def profile_at(self, z: float) -> dict:
        """Return {B, a, dB_dz, da_dz} at axial position z.

        Derivatives are computed analytically from the piecewise B(z) model.
        In the central cell they are zero; in the throat they follow from
        differentiating the sin² profile.
        """
        abs_z = abs(z)
        sign = 1.0 if z >= 0 else -1.0

        if abs_z <= self._L_c / 2:
            # Central cell: uniform field
            B_val = self._B_c
            dB_dz = 0.0
        else:
            z_th = abs_z - self._L_c / 2
            if z_th <= self._L_th:
                # Throat: sin² rise
                theta = math.pi * z_th / (2 * self._L_th)
                B_val = self._B_c * (
                    1 + (self._R_mc - 1) * math.sin(theta) ** 2
                )
                # dB/dz = B_c * (R_mc-1) * sin(2θ) * π/(2 L_th)
                dB_dz_abs = (
                    self._B_c
                    * (self._R_mc - 1)
                    * math.sin(2 * theta)
                    * math.pi
                    / (2 * self._L_th)
                )
                dB_dz = dB_dz_abs * sign
            else:
                # Mirror peak: constant field
                B_val = self._B_c * self._R_mc
                dB_dz = 0.0

        a_val = self._a_c * math.sqrt(self._B_c / B_val)
        da_dz = -a_val * dB_dz / (2 * B_val)

        return {"B": B_val, "a": a_val, "dB_dz": dB_dz, "da_dz": da_dz}


register_geometry("sin2_simple", Sin2SimpleGeometry)
