"""Static regressions for BORAY-like mirror frontend geometry."""

from __future__ import annotations

import os
import math


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_mirror_shape_uses_boray_like_flux_grid_contours_not_hand_lines():
    src = open(INDEX, encoding="utf-8").read()
    mirror_src = src.split("}else if(CUR==='mirror'){", 1)[1].split("}else if(CUR==='frc'){", 1)[0]
    assert "L_c:['有效中心室长','effective cell length','m','geo','L<sub>c</sub>']" in src
    assert "let MIRROR_VIEW=(()=>{try{return localStorage.getItem('polyfusion_mirror_view')||'half'}catch(e){return'half'}})()" in src
    assert 'data-mirror-view="half"' in src
    assert 'data-mirror-view="full"' in src
    assert "const LcEff=v.L_c,a=v.a_c,Rm=v.R_mirror||10,ft=(v.f_throat!=null?v.f_throat:0.1),gg=v.g||0;" in src
    assert "const Lth=ft*LcEff,Z=[],Rr=[];" in src
    assert "const zt=LcEff/2+Lth,zpad=Math.max(Lth*0.18,LcEff*0.015,1e-6);" in src
    assert "const mirrorEase=q=>q*q*q*(10+q*(-15+6*q));" in src
    assert "const mirrorLoop=(z,zc,A)=>A*A/Math.pow(A*A+(z-zc)*(z-zc),1.5);" in src
    assert "const mirrorPair=(z,A)=>mirrorLoop(z,zt,A)+mirrorLoop(z,-zt,A);" in src
    assert "const mirrorVisibleR=0.75,mirrorVisibleB=1/(mirrorVisibleR*mirrorVisibleR);" in src
    assert "let mirrorCoilLo=Math.max(a*0.05,1e-6),mirrorCoilHi=Math.max(a+gg,a*1.05,mirrorCoilLo*1.2);" in src
    assert "const mirrorBhatFor=A=>{const s0=mirrorPair(0,A),st=mirrorPair(zt,A),bias=Math.max(0,(st-Rm*s0)/Math.max(Rm-1,1e-6));return z=>(bias+mirrorPair(z,A))/Math.max(bias+s0,1e-12);};" in src
    assert "for(let k=0;k<28 && mirrorBhatFor(mirrorCoilHi)(LcEff/2)<mirrorVisibleB;k++)mirrorCoilHi*=1.25;" in src
    assert "for(let k=0;k<42;k++){const mid=(mirrorCoilLo+mirrorCoilHi)/2;if(mirrorBhatFor(mid)(LcEff/2)<mirrorVisibleB)mirrorCoilLo=mid;else mirrorCoilHi=mid;}" in src
    assert "const mirrorBhat=mirrorBhatFor(mirrorCoilHi);" in src
    assert "const mirrorCurv=z=>Math.min(mirrorB2(z),0);" in src
    assert "const mirrorBzRZ=(z,r)=>Math.max(0.05,mirrorBhat(z)-0.25*r*r*mirrorCurv(z));" in src
    assert "const mirrorPsiAt=(z,r)=>{const x=Math.abs(r)/Math.max(a,1e-9);return mirrorBhat(z)*x*x-0.125*a*a*mirrorCurv(z)*Math.pow(x,4);};" in src
    assert "mirrorBProfile" not in mirror_src
    assert "mirrorCenterBow" not in mirror_src
    assert "mirrorRadialDrop" not in mirror_src
    assert "const mirrorB2=z=>{const h=Math.max(zt/260,1e-4);return (mirrorBhat(z+h)-2*mirrorBhat(z)+mirrorBhat(z-h))/(h*h);};" in src
    assert "const mirrorBzRZ=(z,r)=>Math.max(0.05,mirrorBhat(z)-0.25*r*r*mirrorCurv(z));" in src
    assert "const mirrorPsiAt=(z,r)=>{const x=Math.abs(r)/Math.max(a,1e-9);return mirrorBhat(z)*x*x-0.125*a*a*mirrorCurv(z)*Math.pow(x,4);};" in src
    assert "const mirrorBoundaryR=z=>{let lo=0,hi=a*1.8;for(let i=0;i<42;i++){const mid=(lo+hi)/2;if(mirrorPsiAt(z,mid)<1)lo=mid;else hi=mid;}return hi;};" in src
    assert "const mirrorHeightCut=mirrorVisibleR*mirrorBoundaryR(0);" in src
    assert "const mirrorThroatS=z=>mirrorEase(Math.max(0,Math.min(1,(mirrorHeightCut-mirrorBoundaryR(z))/Math.max(mirrorHeightCut-mirrorBoundaryR(zt),1e-6))));" in src
    assert "const mirrorCenterEdgeZ=()=>{if(mirrorBoundaryR(zt)>mirrorHeightCut)return zt;let lo=0,hi=zt;for(let i=0;i<40;i++){const mid=(lo+hi)/2;if(mirrorBoundaryR(mid)>mirrorHeightCut)lo=mid;else hi=mid;}return hi;};" in src
    assert "const mirrorThroatCut=0.85*Math.max(Rm,1e-6);" not in src
    assert "mirrorCoreRise" not in mirror_src
    assert "mirrorPsiNorm" not in mirror_src
    assert "rho=r/rb" not in mirror_src
    assert "return rho*rho" not in mirror_src
    assert "mirrorPeak" not in src
    assert "mirrorBaxis" not in src
    assert "mirrorBaxis2" not in src
    assert "prof=z" not in src
    assert "mirrorW=Math.max(Lth*1.35,Lc*0.16" not in src
    assert "Lc*0.16" not in src
    assert "const zc=mirrorCenterEdgeZ();" in src
    assert "const dimSeg=(x1,x2,y,c,ds='dot')=>add({type:'scatter',mode:'lines+markers',x:[x1,x2],y:[y,y]," in src
    assert "const yLc=a*0.11,yEff=mirrorHeightCut,yLth=Math.max(a*0.72,yEff+a*0.20);" in src
    assert "dimSeg(-LcEff/2,LcEff/2,yLc,'#ffc247','dot');" in src
    assert "L<sub>c</sub>=${(+LcEff).toFixed(2)} m" in src
    assert "dimSeg(LcEff/2,zt,yLth,'#ff9e3d','dash');dimSeg(-zt,-LcEff/2,yLth,'#ff9e3d','dash');" in src
    assert "L<sub>th</sub>=${(+Lth).toFixed(2)} m" in src
    assert "add(cv([-zc,zc],[yEff,yEff],'#ffd166',2.0,'dash'),'annot');" in src
    assert "add(cv([zc,zc],[MIRROR_VIEW==='full'?-yEff:0,mirrorBoundaryR(zc)],'#ffd166',1.5,'dot'),'annot');" in src
    assert "add(cv([-zc,-zc],[MIRROR_VIEW==='full'?-yEff:0,mirrorBoundaryR(-zc)],'#ffd166',1.5,'dot'),'annot');" in src
    assert "marker:{color:'#ffd166',size:8,symbol:'circle-open',line:{color:'#ffd166',width:2}}" in src
    assert "R=0.75R<sub>max</sub>" in src
    assert "for(let i=0;i<=220;i++){const z=zmin+(zmax-zmin)*i/220;Z.push(z);Rr.push(mirrorBoundaryR(z));}" in src
    assert "const mirrorPsiGrid=(sgn=1)=>{const nx=361,ny=181" in src
    assert "const psi=x.map(()=>0),prevB=x.map(z=>mirrorBzRZ(z,0));let prevR=0;" in src
    assert "psi[i]+=(r-prevR)*0.5*(bz+prevB[i])*0.5*(r+prevR)/(0.5*a*a);" in src
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


def _mirror_frontend_model(Lc_eff: float, fth: float, Rm: float, a: float, g: float):
    Lth = fth * Lc_eff
    zt = Lc_eff / 2 + Lth

    def loop(z: float, zc: float, A: float) -> float:
        return A * A / ((A * A + (z - zc) * (z - zc)) ** 1.5)

    def pair(z: float, A: float) -> float:
        return loop(z, zt, A) + loop(z, -zt, A)

    visible_r = 0.75
    visible_b = 1 / (visible_r * visible_r)
    coil_lo = max(a * 0.05, 1e-6)
    coil_hi = max(a + g, a * 1.05, coil_lo * 1.2)

    def bhat_for(A: float):
        s0 = pair(0, A)
        st = pair(zt, A)
        bias = max(0, (st - Rm * s0) / max(Rm - 1, 1e-6))

        def inner(z: float) -> float:
            return (bias + pair(z, A)) / max(bias + s0, 1e-12)

        return inner

    for _ in range(28):
        if bhat_for(coil_hi)(Lc_eff / 2) >= visible_b:
            break
        coil_hi *= 1.25

    for _ in range(42):
        mid = (coil_lo + coil_hi) / 2
        if bhat_for(mid)(Lc_eff / 2) < visible_b:
            coil_lo = mid
        else:
            coil_hi = mid

    bhat = bhat_for(coil_hi)

    def b2(z: float) -> float:
        h = max(zt / 260, 1e-4)
        return (bhat(z + h) - 2 * bhat(z) + bhat(z - h)) / (h * h)

    def curv(z: float) -> float:
        return min(b2(z), 0)

    def psi(z: float, r: float) -> float:
        x = abs(r) / max(a, 1e-9)
        return bhat(z) * x * x - 0.125 * a * a * curv(z) * x**4

    def boundary_r(z: float) -> float:
        lo = 0
        hi = a * 1.8
        for _ in range(42):
            mid = (lo + hi) / 2
            if psi(z, mid) < 1:
                lo = mid
            else:
                hi = mid
        return hi

    def center_edge_z() -> float:
        height_cut = visible_r * boundary_r(0)
        if boundary_r(zt) > height_cut:
            return zt
        lo = 0
        hi = zt
        for _ in range(40):
            mid = (lo + hi) / 2
            if boundary_r(mid) > height_cut:
                lo = mid
            else:
                hi = mid
        return hi

    return zt, bhat, boundary_r, center_edge_z


def test_mirror_throat_fraction_half_stays_monotone_without_boundary_overshoot():
    cases = [
        (10, 0.5, 10, 0.3, 0.05),
        (7, 0.5, 35, 0.15, 0.03),
        (7, 0.15, 35, 0.15, 0.03),
        (1, 0.5, 35, 0.15, 0.03),
    ]
    for Lc, fth, Rm, a, g in cases:
        zt, bhat, boundary_r, center_edge_z = _mirror_frontend_model(Lc, fth, Rm, a, g)
        Lth = fth * Lc
        zs = [Lc / 2 + Lth * i / 40 for i in range(41)]
        bs = [bhat(z) for z in zs]
        rs = [boundary_r(z) for z in zs]

        assert math.isclose(bhat(0), 1.0, rel_tol=1e-9, abs_tol=1e-9)
        assert bhat(Lc / 4) > bhat(0) + 1e-3
        assert math.isclose(boundary_r(Lc / 2), 0.75 * boundary_r(0), rel_tol=1.5e-2, abs_tol=1.5e-2)
        assert math.isclose(bhat(zt), Rm, rel_tol=2e-3, abs_tol=2e-3)
        assert math.isclose(2 * center_edge_z(), Lc, rel_tol=1.5e-2, abs_tol=1.5e-2)
        assert all(bs[i] <= bs[i + 1] + 1e-9 for i in range(len(bs) - 1))
        assert all(r <= a * 1.002 for r in rs)
