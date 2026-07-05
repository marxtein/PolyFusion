"""Static regressions for BORAY-like mirror frontend geometry."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_like_flux_grid_contours_not_hand_lines():
    src = open(INDEX, encoding="utf-8").read()
    mirror_src = src.split("}else if(CUR==='mirror'){", 1)[1].split("}else if(CUR==='frc'){", 1)[0]
    assert "let MIRROR_VIEW=(()=>{try{return localStorage.getItem('polyfusion_mirror_view')||'half'}catch(e){return'half'}})()" in src
    assert 'data-mirror-view="half"' in src
    assert 'data-mirror-view="full"' in src
    assert "const zt=Lc/2+Lth,zpad=Math.max(Lth*0.18,Lc*0.015,1e-6)" in src
    assert "const mirrorEase=q=>q*q*q*(10+q*(-15+6*q));" in src
    assert "const mirrorShapeS=z=>{const p=Math.max(0,Math.min(1,Math.abs(z)/Math.max(zt,1e-6))),u=0.25*p*p+0.75*Math.pow(p,8);return u*(2-u);};" in src
    assert "const mirrorBhat=z=>{const s=mirrorShapeS(z),rt=1/Math.sqrt(Math.max(Rm,1e-6)),rb=1-s+s*rt;return 1/(rb*rb);};" in src
    assert "const mirrorThroatCut=0.85*Math.max(Rm,1e-6);" in src
    assert "const mirrorThroatS=z=>mirrorEase(Math.max(0,Math.min(1,(mirrorBhat(z)-mirrorThroatCut)/Math.max(Math.max(Rm,1e-6)-mirrorThroatCut,1e-6))));" in src
    assert "const mirrorCenterEdgeZ=()=>{if(mirrorBhat(0)>=mirrorThroatCut)return 0;if(mirrorBhat(zt)<mirrorThroatCut)return zt;let lo=0,hi=zt;for(let i=0;i<40;i++){const mid=(lo+hi)/2;if(mirrorBhat(mid)<mirrorThroatCut)lo=mid;else hi=mid;}return hi;};" in src
    assert "const mirrorBoundaryR=z=>{const s=mirrorShapeS(z),rt=1/Math.sqrt(Math.max(Rm,1e-6));return a*(1-s+s*rt);};" in src
    assert "const mirrorCoreRise=Math.min(0.36,0.010*(Rm-1));" in src
    assert "const mirrorPsiNorm=(z,r)=>{const rb=Math.max(mirrorBoundaryR(z),1e-9),rho=r/rb,p=Math.min(1,Math.abs(z)/Math.max(zt,1e-6)),th=mirrorThroatS(z);" in src
    assert "const bow=1+mirrorCoreRise*Math.max(0,1-rho*rho)*(1-p*p)*(1-0.55*th);return rho*rho/bow;};" in src
    assert "mirrorPeak" not in src
    assert "mirrorBaxis" not in src
    assert "mirrorBaxis2" not in src
    assert "mirrorBzRZ" not in src
    assert "mirrorPsiAt" not in src
    assert "prof=z" not in src
    assert "mirrorW=Math.max(Lth*1.35,Lc*0.16" not in src
    assert "Lc*0.16" not in src
    assert "const zc=mirrorCenterEdgeZ();" in src
    assert "const dimSeg=(x1,x2,y,c,ds='dot')=>add({type:'scatter',mode:'lines+markers',x:[x1,x2],y:[y,y]," in src
    assert "const yLc=a*0.11,yLth=a*0.43;" in src
    assert "dimSeg(-Lc/2,Lc/2,yLc,'#ffc247','dot');" in src
    assert "L<sub>c</sub>=${(+Lc).toFixed(2)} m" in src
    assert "dimSeg(Lc/2,zt,yLth,'#ff9e3d','dash');dimSeg(-zt,-Lc/2,yLth,'#ff9e3d','dash');" in src
    assert "L<sub>th</sub>=${(+Lth).toFixed(2)} m" in src
    assert "add(cv([-zc,zc],[a*0.20,a*0.20],'#ffd166',1.4,'dot'),'annot');" in src
    assert "L<sub>c,eff</sub>≈${(2*zc).toFixed(2)} m" in src
    assert "for(let i=0;i<=220;i++){const z=zmin+(zmax-zmin)*i/220;Z.push(z);Rr.push(mirrorBoundaryR(z));}" in src
    assert "const mirrorPsiGrid=(sgn=1)=>{const nx=361,ny=181" in src
    assert "for(let i=0;i<nx;i++)row.push(mirrorPsiNorm(x[i],r));" in src
    assert "return{x,y:yb.map(r=>-r).reverse(),z:[...zb].reverse()};" in src
    assert "const mirrorContour=(sgn,start,end,size,width,grp)=>{const g=mirrorPsiGrid(sgn),c=GC(grp==='boundary'?'boundary':'flux');" in src
    assert "type:'contour'" in mirror_src
    assert "line:{color:c,width,smoothing:1.25}" in src
    assert "mirrorFluxLine" not in mirror_src
    assert "mirrorFluxLevels" not in mirror_src
    assert "type:'heatmap'" not in mirror_src
    assert "mirrorBackdrop" not in mirror_src
    assert "mirrorRay" not in mirror_src
    assert "background/rays are visual guides" not in mirror_src
    assert "#ffe45c" not in mirror_src
    assert "#f59e0b" not in mirror_src
    assert "#168ac6" not in mirror_src
    assert "if(MIRROR_VIEW==='full')" in src
    assert "const mirrorFill=(x,y)=>add({type:'scatter',mode:'lines',x,y,line:{color:'rgba(0,0,0,0)',width:0},fill:'toself'" in src
    assert "mirrorFill(Zb,Rb);mirrorContour(1,1,1,1,2.6,'boundary');mirrorContour(-1,1,1,1,2.6,'boundary');" in src
    assert "mirrorContour(1,0.08,0.68,0.05,1.05,'flux');mirrorContour(-1,0.08,0.68,0.05,1.05,'flux');" in src
    assert "mirrorFill(Zb,Rb);mirrorContour(1,1,1,1,2.6,'boundary');" in src
    assert "mirrorContour(1,0.08,0.68,0.05,1.05,'flux');" in src
    assert "BORAY-like open flux-tube field lines" in src
    assert "full view mirrors the half-plane" in src
    assert "Z-R half-plane" in src
    assert "lay.yaxis.range=MIRROR_VIEW==='full'?[-(a+gg)*1.75,(a+gg)*1.75]:[0,(a+gg)*1.75]" in src
    assert "[0.35,0.65,0.88].forEach" not in src
