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
    assert "const zt=Lc/2+Lth,zpad=Math.max(Lth*0.18,Lc*0.015,1e-6)" in src
    assert "const mirrorEase=q=>q*q*q*(10+q*(-15+6*q));" in src
    assert "const mirrorThroatS=z=>mirrorEase(Math.max(0,Math.min(1,(Math.abs(z)-Lc/2)/Math.max(Lth,1e-6))));" in src
    assert "const mirrorBoundaryR=z=>{const s=mirrorThroatS(z),rt=1/Math.sqrt(Math.max(Rm,1e-6));return a*(1-s+s*rt);};" in src
    assert "const mirrorCoreU=z=>{const q=Math.min(1,Math.abs(z)/Math.max(Lc/2,1e-6));return q*q*(3-2*q);}" in src
    assert "const mirrorCoreRise=Math.min(0.45,0.013*(Rm-1))" in src
    assert "const mirrorCoreBow=z=>1+mirrorCoreRise*(1-0.45*mirrorCoreU(z))*(1-mirrorThroatS(z));" in src
    assert "const mirrorPsiNorm=(z,r)=>Math.pow(r/Math.max(mirrorBoundaryR(z),1e-9),2)/mirrorCoreBow(z);" in src
    assert "mirrorPeak" not in src
    assert "mirrorBaxis" not in src
    assert "mirrorBaxis2" not in src
    assert "mirrorBzRZ" not in src
    assert "mirrorPsiAt" not in src
    assert "prof=z" not in src
    assert "mirrorW=Math.max(Lth*1.35,Lc*0.16" not in src
    assert "Lc*0.16" not in src
    assert "for(let i=0;i<=220;i++){const z=zmin+(zmax-zmin)*i/220;Z.push(z);Rr.push(mirrorBoundaryR(z));}" in src
    assert "const mirrorPsiGrid=(sgn=1)=>{const nx=241,ny=121" in src
    assert "for(let i=0;i<nx;i++)row.push(mirrorPsiNorm(x[i],r));" in src
    assert "return{x,y:yb.map(r=>-r).reverse(),z:[...zb].reverse()}" in src
    assert "const mirrorPsiContour=(sgn=1)=>{const g=mirrorPsiGrid(sgn),c=GC('flux')" in src
    assert "type:'contour'" in src
    assert "start:0.08,end:0.68,size:0.055" in src
    assert "colorscale:[[0,c],[1,c]]" in src
    assert "const mirrorBackdrop=(sgn=1)=>{const nx=181,ny=82" in src
    assert "type:'heatmap'" in src
    assert "colorscale:[[0,'#ffe45c'],[0.34,'#44d8dd'],[0.68,'#4276dc'],[1,'#6f55cf']]" in src
    assert "background/rays are visual guides" in src
    assert "const mirrorRay=(off,c,sgn=1)=>{const x=[],y=[]" in src
    assert "if(MIRROR_VIEW==='full')" in src
    assert "const mirrorFill=(x,y)=>add({type:'scatter',mode:'lines',x,y,line:{color:'rgba(0,0,0,0)',width:0},fill:'toself'" in src
    assert "tr.push(mirrorBackdrop(1));tr.push(mirrorBackdrop(-1));" in src
    assert "add(cv(Z,Rr,GC('flux'),1.45),'boundary');add(cv(Z,Rn,GC('flux'),1.45),'boundary');mirrorFill(Zb,Rb);" in src
    assert "add(mirrorPsiContour(1),'flux');add(mirrorPsiContour(-1),'flux')" in src
    assert "mirrorRay(0,'#f59e0b',1)" in src
    assert "mirrorRay(0,'#f59e0b',-1)" in src
    assert "tr.push(mirrorBackdrop(1));" in src
    assert "add(cv(Z,Rr,GC('flux'),1.45),'boundary');mirrorFill(Zb,Rb);" in src
    assert "add(mirrorPsiContour(1),'flux');" in src
    assert "BORAY-like open flux-tube contours" in src
    assert "Z-R half-plane with visual background/ray guides" in src
    assert "lay.yaxis.range=MIRROR_VIEW==='full'?[-(a+gg)*1.75,(a+gg)*1.75]:[0,(a+gg)*1.75]" in src
    assert "[0.35,0.65,0.88].forEach" not in src
