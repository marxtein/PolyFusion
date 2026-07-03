"""Static regressions for BORAY-style mirror frontend geometry."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_style_psi_contours_not_scaled_hand_lines():
    src = open(INDEX, encoding="utf-8").read()
    assert "const mirrorBnorm=z=>" in src
    assert "const mirrorPsiNorm=(z,r)=>mirrorBnorm(z)*Math.pow(r/(a||1e-12),2)" in src
    assert "const mirrorPsiGrid=()=>{const nx=241,ny=121" in src
    assert "const mirrorPsiContour=()=>{const g=mirrorPsiGrid(),c=GC('flux')" in src
    assert "type:'contour'" in src
    assert "start:0.16,end:0.76,size:0.30" in src
    assert "colorscale:[[0,c],[1,c]]" in src
    assert "add(mirrorPsiContour(),'flux')" in src
    assert "BORAY-style psi contours" in src
    assert "[0.35,0.65,0.88].forEach" not in src

