"""Static regressions for BORAY-style mirror frontend geometry."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_style_psi_contours_not_scaled_hand_lines():
    src = open(INDEX, encoding="utf-8").read()
    assert "const mirrorBnorm=z=>" in src
    assert "const mirrorPsiNorm=(z,r)=>mirrorBnorm(z)*Math.pow(r/(a||1e-12),2)" in src
    assert "const mirrorPsiGrid=(sgn=1)=>{const nx=241,ny=121" in src
    assert "return{x,y:yb.map(r=>-r).reverse(),z:[...zb].reverse()}" in src
    assert "const mirrorPsiContour=(sgn=1)=>{const g=mirrorPsiGrid(sgn),c=GC('flux')" in src
    assert "type:'contour'" in src
    assert "start:0.16,end:0.76,size:0.30" in src
    assert "colorscale:[[0,c],[1,c]]" in src
    assert "add(mirrorPsiContour(1),'flux');add(mirrorPsiContour(-1),'flux')" in src
    assert "BORAY-style psi contours" in src
    assert "full Z-R plane with both radius signs" in src
    assert "lay.yaxis.range=[-(a+gg)*1.75,(a+gg)*1.75]" in src
    assert "[0.35,0.65,0.88].forEach" not in src
