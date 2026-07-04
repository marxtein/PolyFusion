"""Static regressions for BORAY-style mirror frontend geometry."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_style_psi_contours_not_scaled_hand_lines():
    src = open(INDEX, encoding="utf-8").read()
    assert "const mirrorBaxis=z=>" in src
    assert "const mirrorBaxis2=z=>" in src
    assert "const mirrorBzRZ=(z,r)=>Math.max(0.05,mirrorBaxis(z)-0.25*r*r*mirrorBaxis2(z))" in src
    assert "const mirrorPsiAt=(z,r)=>{const n=28,dr=r/n,norm=0.5*a*a;let psi=0,br0=mirrorBzRZ(z,0)" in src
    assert "const mirrorPsiGrid=(sgn=1)=>{const nx=241,ny=121" in src
    assert "row.push(prev+dr*0.5*(mirrorBzRZ(x[i],r)+mirrorBzRZ(x[i],rp))*0.5*(r+rp)/Math.max(0.5*a*a,1e-12))" in src
    assert "return{x,y:yb.map(r=>-r).reverse(),z:[...zb].reverse()}" in src
    assert "const mirrorPsiContour=(sgn=1)=>{const g=mirrorPsiGrid(sgn),c=GC('flux')" in src
    assert "type:'contour'" in src
    assert "start:0.12,end:0.90,size:0.13" in src
    assert "colorscale:[[0,c],[1,c]]" in src
    assert "add(mirrorPsiContour(1),'flux');add(mirrorPsiContour(-1),'flux')" in src
    assert "BORAY-style psi contours" in src
    assert "full Z-R plane with both radius signs" in src
    assert "lay.yaxis.range=[-(a+gg)*1.75,(a+gg)*1.75]" in src
    assert "[0.35,0.65,0.88].forEach" not in src
