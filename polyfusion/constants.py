"""Physical constants for the ETSC 0-D system code.

Values mirror the authoritative MATLAB / JS reference implementations
(``funsc.m`` and ``etsc.html``) so that results are reproducible.
"""

QE = 1.6022e-19        # elementary charge [C]
MP = 1.6726e-27        # proton mass [kg]
ME = 9.1094e-31        # electron mass [kg]
MU0 = 4e-7 * 3.141592653589793  # vacuum permeability [H/m]
MEC2 = 511.0           # electron rest energy [keV]

# Nucleon-count based ion masses used in the reactivity integral.
M_D = 2 * MP           # deuteron
M_T = 3 * MP           # triton
M_HE3 = 3 * MP         # helium-3
M_B11 = 11 * MP        # boron-11
