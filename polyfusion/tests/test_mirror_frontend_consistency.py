"""Static regressions for BORAY-style mirror frontend geometry."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_style_psi_contours_not_scaled_hand_lines():
    src = open(INDEX, encoding="utf-8").read()
    assert "let MIRROR_VIEW=(()=>{try{return localStorage.getItem('polyfusion_mirror_view')||'half'}catch(e){return'half'}})()" in src
    assert 'data-mirror-view="half"' in src
    assert 'data-mirror-view="full"' in src
    assert "const mirrorBaxis=z=>" in src
    assert "const zt=Lc/2+Lth,zpad=Math.max(Lth*0.18,Lc*0.015,1e-6)" in src
    assert "const mirrorW=Math.max(Lth*0.45,Lc*0.01,1e-6)" in src
    assert "const mirrorPeak=(z,z0)=>Math.exp(-Math.pow((z-z0)/mirrorW,2))" in src
    assert "const mirrorBaxis=z=>{const g0=2*Math.exp(-Math.pow(zt/mirrorW,2)),gp=1+Math.exp(-Math.pow((2*zt)/mirrorW,2))" in src
    assert "mirrorW=Math.max(Lth*1.35,Lc*0.16" not in src
    assert "Lc*0.16" not in src
    assert "const mirrorBaxis2=z=>" in src
    assert "const mirrorBzRZ=(z,r)=>Math.max(0.05,mirrorBaxis(z)-0.25*r*r*mirrorBaxis2(z))" in src
    assert "const mirrorPsiAt=(z,r)=>{const n=28,dr=r/n,norm=0.5*a*a;let psi=0,br0=mirrorBzRZ(z,0)" in src
    assert "const prof=z=>{let lo=0,hi=a*1.02;for(let k=0;k<28;k++)" in src
    assert "const mirrorPsiGrid=(sgn=1)=>{const nx=241,ny=121" in src
    assert "row.push(prev+dr*0.5*(mirrorBzRZ(x[i],r)+mirrorBzRZ(x[i],rp))*0.5*(r+rp)/Math.max(0.5*a*a,1e-12))" in src
    assert "return{x,y:yb.map(r=>-r).reverse(),z:[...zb].reverse()}" in src
    assert "const mirrorPsiContour=(sgn=1)=>{const g=mirrorPsiGrid(sgn),c=GC('flux')" in src
    assert "type:'contour'" in src
    assert "start:0.12,end:0.90,size:0.13" in src
    assert "colorscale:[[0,c],[1,c]]" in src
    assert "if(MIRROR_VIEW==='full')" in src
    assert "const mirrorFill=(x,y)=>add({type:'scatter',mode:'lines',x,y,line:{color:'rgba(0,0,0,0)',width:0},fill:'toself'" in src
    assert "add(mirrorPsiContour(1),'flux');add(mirrorPsiContour(-1),'flux')" in src
    assert "add(mirrorPsiContour(1),'flux');" in src
    assert "BORAY-style psi contours" in src
    assert "full view mirrors the half-plane" in src
    assert "Z-R axisymmetric half-plane" in src
    assert "lay.yaxis.range=MIRROR_VIEW==='full'?[-(a+gg)*1.75,(a+gg)*1.75]:[0,(a+gg)*1.75]" in src
    assert "[0.35,0.65,0.88].forEach" not in src
