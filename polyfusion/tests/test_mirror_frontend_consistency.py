"""Static regressions for BORAY-like mirror frontend geometry."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_like_smooth_field_lines_not_colored_style_layers():
    src = open(INDEX, encoding="utf-8").read()
    mirror_src = src.split("}else if(CUR==='mirror'){", 1)[1].split("}else if(CUR==='frc'){", 1)[0]
    assert "let MIRROR_VIEW=(()=>{try{return localStorage.getItem('polyfusion_mirror_view')||'half'}catch(e){return'half'}})()" in src
    assert 'data-mirror-view="half"' in src
    assert 'data-mirror-view="full"' in src
    assert "const zt=Lc/2+Lth,zpad=Math.max(Lth*0.18,Lc*0.015,1e-6)" in src
    assert "const mirrorEase=q=>q*q*q*(10+q*(-15+6*q));" in src
    assert "const mirrorTurnIn=Math.min(Lth*0.62,Lc*0.12);" in src
    assert "const mirrorThroatS=z=>mirrorEase(Math.max(0,Math.min(1,(Math.abs(z)-(Lc/2-mirrorTurnIn))/Math.max(Lth+mirrorTurnIn,1e-6))));" in src
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
    assert "const mirrorFluxLevels=Array.from({length:13},(_,i)=>0.08+i*0.05);" in src
    assert "const mirrorFluxLine=(level,sgn=1)=>{const x=[],y=[];" in src
    assert "for(let i=0;i<=360;i++){const z=zmin+(zmax-zmin)*i/360;" in src
    assert "sgn*mirrorBoundaryR(z)*Math.sqrt(Math.max(0,level*mirrorCoreBow(z)))" in src
    assert "type:'heatmap'" not in mirror_src
    assert "mirrorBackdrop" not in mirror_src
    assert "mirrorRay" not in mirror_src
    assert "background/rays are visual guides" not in mirror_src
    assert "#ffe45c" not in mirror_src
    assert "#f59e0b" not in mirror_src
    assert "#168ac6" not in mirror_src
    assert "if(MIRROR_VIEW==='full')" in src
    assert "const mirrorFill=(x,y)=>add({type:'scatter',mode:'lines',x,y,line:{color:'rgba(0,0,0,0)',width:0},fill:'toself'" in src
    assert "add(cv(Z,Rr,GC('flux'),1.45),'boundary');add(cv(Z,Rn,GC('flux'),1.45),'boundary');mirrorFill(Zb,Rb);" in src
    assert "mirrorFluxLevels.forEach(lv=>{add(mirrorFluxLine(lv,1),'flux');add(mirrorFluxLine(lv,-1),'flux');});" in src
    assert "add(cv(Z,Rr,GC('flux'),1.45),'boundary');mirrorFill(Zb,Rb);" in src
    assert "mirrorFluxLevels.forEach(lv=>add(mirrorFluxLine(lv,1),'flux'));" in src
    assert "BORAY-like open flux-tube field lines" in src
    assert "full view mirrors the half-plane" in src
    assert "Z-R half-plane" in src
    assert "lay.yaxis.range=MIRROR_VIEW==='full'?[-(a+gg)*1.75,(a+gg)*1.75]:[0,(a+gg)*1.75]" in src
    assert "[0.35,0.65,0.88].forEach" not in src
