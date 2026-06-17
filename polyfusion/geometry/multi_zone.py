"""Multi-zone mirror geometry with independent throat length, expander, and
switchable B(z) profile.

Three axial zones (symmetric, right half-plane |z|):

  Zone 1 — Central Cell:  |z| <= L_c/2
    B(z) = B_c = B_vac * sqrt(1 - beta)        (uniform)
    a(z) = a_c                                   (uniform)

  Zone 2 — Throat / Transition:  L_c/2 < |z| <= L_c/2 + L_th
    B(z) = B_c + (R_mirror * B_vac - B_c) * f(x)
    x = (|z| - L_c/2) / L_th  in  [0, 1]
    f(0)=0,  f(1)=1,  f'(0)=f'(1)=0
    a(z) = a_c * sqrt(B_c / B(z))               (flux conservation)

  Zone 3 — Expander:  L_c/2 + L_th < |z| <= L_c/2 + L_th + L_expand
    B(z) decays linearly from B_mirror to B_collector = B_mirror / B_expand
    a(z) = a_c * sqrt(B_c / B(z))

Register via: ``register_geometry("multi_zone", MultiZoneGeometry)``.
"""

from __future__ import annotations

import math

import numpy as np

from .base import MirrorGeometry, register_geometry


class MultiZoneGeometry(MirrorGeometry):
    """Multi-zone axial mirror geometry.

    Supports two B(z) profile families in the throat region via the
    ``profile`` parameter:

    * ``"hermite"`` (default) — cubic smoothstep: f(x) = 3*x² - 2*x³
    * ``"sin2"`` — sinusoidal: f(x) = sin²(π*x/2)

    Key improvements over the legacy sin²-simple model:

    1. ``L_th`` is independent of ``L_c``
    2. B(z) profile switchable ("hermite" or "sin2")
    3. Wall area includes throat and expander regions
    4. ``f_axial`` attenuation factor for n,T at throat (stored, applied downstream)
    5. Explicit expander zone with linear B decay
    """

    def __init__(
        self,
        a_c: float,
        L_c: float,
        B_vac: float,
        R_mirror: float,
        beta: float,
        L_th: float = 1.0,
        g: float = 0.0,
        profile: str = "hermite",
        f_axial: float = 0.8,
        L_expand: float = 2.0,
        B_expand: float = 100.0,
    ) -> None:
        # -- store parameters --------------------------------------------------
        self.a_c = a_c
        self.L_c = L_c
        self.B_vac = B_vac
        self.R_mirror = R_mirror
        self.beta = beta
        self.L_th = L_th
        self.g = g
        self.profile = profile
        self.f_axial = f_axial
        self.L_expand = L_expand
        self.B_expand = B_expand

        # -- derived field values ----------------------------------------------
        self._B_c = B_vac * math.sqrt(max(1.0 - beta, 0.0))
        self._B_mirror = R_mirror * B_vac
        self._B_collector = self._B_mirror / B_expand

        # -- axial zone boundaries (right half-plane, z >= 0) ------------------
        self._z_cc = L_c / 2.0
        self._z_mirror = self._z_cc + L_th
        self._z_collector = self._z_mirror + L_expand

        # -- pre-compute global quantities (volumes, areas) --------------------
        self._precompute()

    # ------------------------------------------------------------------
    #  Profile helpers (right half-plane only, z >= 0)
    # ------------------------------------------------------------------

    def _f_throat(self, x: float) -> float:
        """Throat profile function f(x), x in [0, 1]."""
        if self.profile == "sin2":
            s = math.sin(math.pi * x / 2.0)
            return s * s
        # hermite (cubic smoothstep)
        return 3.0 * x * x - 2.0 * x * x * x

    def _df_throat(self, x: float) -> float:
        """Derivative f'(x) of the throat profile function."""
        if self.profile == "sin2":
            return math.pi / 2.0 * math.sin(math.pi * x)
        # hermite
        return 6.0 * x - 6.0 * x * x

    def _B_at(self, z_abs: float) -> float:
        """On-axis B(z) for the right half-plane (z >= 0)."""
        if z_abs <= self._z_cc:
            return self._B_c
        if z_abs <= self._z_mirror:
            x = (z_abs - self._z_cc) / self.L_th
            return self._B_c + (self._B_mirror - self._B_c) * self._f_throat(x)
        if z_abs <= self._z_collector:
            frac = (z_abs - self._z_mirror) / self.L_expand
            return self._B_mirror + (self._B_collector - self._B_mirror) * frac
        return self._B_collector

    def _a_at(self, z_abs: float) -> float:
        """Plasma radius a(z) for the right half-plane, via flux conservation."""
        return self.a_c * math.sqrt(self._B_c / self._B_at(z_abs))

    def _dB_dz_at(self, z_abs: float) -> float:
        """dB/dz for the right half-plane (z >= 0)."""
        if z_abs <= self._z_cc:
            return 0.0
        if z_abs <= self._z_mirror:
            x = (z_abs - self._z_cc) / self.L_th
            return (self._B_mirror - self._B_c) * self._df_throat(x) / self.L_th
        if z_abs <= self._z_collector:
            return (self._B_collector - self._B_mirror) / self.L_expand
        return 0.0

    def _da_dz_at(self, z_abs: float) -> float:
        """da/dz for the right half-plane.

        da/dz = -(a_c/2) * sqrt(B_c) * B(z)^(-3/2) * dB/dz
        """
        B = self._B_at(z_abs)
        dB_dz = self._dB_dz_at(z_abs)
        return -0.5 * self.a_c * math.sqrt(self._B_c) * B ** (-1.5) * dB_dz

    # ------------------------------------------------------------------
    #  Numerical pre-computation of global quantities
    # ------------------------------------------------------------------

    def _precompute(self) -> None:
        """Compute volume, surface, and wall area and cache them."""

        def _simpson(f, a, b, n=81):
            """Composite Simpson's rule on [a, b] with n points (n odd)."""
            if n % 2 == 0:
                n += 1
            x = np.linspace(a, b, n)
            h = (b - a) / (n - 1)
            y = np.array([f(xi) for xi in x])
            return h / 3.0 * (
                y[0] + y[-1] + 4.0 * np.sum(y[1:-1:2]) + 2.0 * np.sum(y[2:-2:2])
            )

        # ---- Plasma volume ---------------------------------------------------
        self._V_cyl = math.pi * self.a_c**2 * self.L_c

        self._V_throat = 0.0
        self._S_throat = 0.0
        if self.L_th > 0:
            self._V_throat = (
                2.0
                * math.pi
                * _simpson(lambda z: self._a_at(z) ** 2, self._z_cc, self._z_mirror)
            )
            self._S_throat = (
                2.0
                * 2.0
                * math.pi
                * _simpson(lambda z: self._a_at(z), self._z_cc, self._z_mirror)
            )

        self._V_expander = 0.0
        self._S_expander = 0.0
        if self.L_expand > 0:
            self._V_expander = (
                2.0
                * math.pi
                * _simpson(lambda z: self._a_at(z) ** 2, self._z_mirror, self._z_collector)
            )
            self._S_expander = (
                2.0
                * 2.0
                * math.pi
                * _simpson(lambda z: self._a_at(z), self._z_mirror, self._z_collector)
            )

        self._Vp = self._V_cyl + self._V_throat + self._V_expander

        # ---- Plasma side surface ---------------------------------------------
        self._Sp = (
            2.0 * math.pi * self.a_c * self.L_c
            + self._S_throat
            + self._S_expander
        )

        # ---- Wall surface (includes gap g) -----------------------------------
        r_w = self.a_c + self.g
        Sw_cyl = 2.0 * math.pi * r_w * self.L_c

        if self.L_th > 0:
            a_throat_avg = float(
                np.mean(
                    [
                        self._a_at(z)
                        for z in np.linspace(self._z_cc, self._z_mirror, 40)
                    ]
                )
            )
            Sw_throat = 2.0 * 2.0 * math.pi * (a_throat_avg + self.g) * self.L_th
        else:
            Sw_throat = 0.0

        if self.L_expand > 0:
            a_exp_avg = float(
                np.mean(
                    [
                        self._a_at(z)
                        for z in np.linspace(self._z_mirror, self._z_collector, 40)
                    ]
                )
            )
            Sw_expander = 2.0 * 2.0 * math.pi * (a_exp_avg + self.g) * self.L_expand
        else:
            Sw_expander = 0.0

        Sw_endplates = 2.0 * math.pi * r_w**2

        self._Sw = Sw_cyl + Sw_throat + Sw_expander + Sw_endplates

        # ---- Throat quantities -----------------------------------------------
        self._a_throat = self.a_c * math.sqrt(self._B_c / self._B_mirror)
        self._A_throat = math.pi * self._a_throat**2

    # ------------------------------------------------------------------
    #  Abstract method implementations
    # ------------------------------------------------------------------

    def volume(self) -> float:
        """Total plasma volume [m^3]."""
        return self._Vp

    def surface(self) -> float:
        """Plasma side surface area [m^2]."""
        return self._Sp

    def wall_surface(self) -> float:
        """First-wall surface area [m^2] (cylinder + throat + expander + endplates)."""
        return self._Sw

    def throat_area(self) -> float:
        """Single throat magnetic flux area [m^2]."""
        return self._A_throat

    def throat_radius(self) -> float:
        """Plasma radius at the mirror throat [m]."""
        return self._a_throat

    def B(self, z: float) -> float:
        """On-axis magnetic field at axial position z [T].

        Mirror-symmetric: B(-z) = B(z).
        """
        return self._B_at(abs(z))

    def a(self, z: float) -> float:
        """Plasma radius at axial position z [m].

        Mirror-symmetric: a(-z) = a(z).
        """
        return self._a_at(abs(z))

    def profile_at(self, z: float) -> dict:
        """Return {B, a, dB_dz, da_dz} at axial position z.

        B and a are even; dB_dz and da_dz are odd (anti-symmetric).
        """
        z_abs = abs(z)
        sign = -1.0 if z < 0 else 1.0
        return {
            "B": self._B_at(z_abs),
            "a": self._a_at(z_abs),
            "dB_dz": sign * self._dB_dz_at(z_abs),
            "da_dz": sign * self._da_dz_at(z_abs),
        }


# Register the geometry so it is discoverable via get_geometry("multi_zone").
register_geometry("multi_zone", MultiZoneGeometry)
