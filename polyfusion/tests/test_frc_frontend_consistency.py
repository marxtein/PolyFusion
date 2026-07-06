"""Static regressions for FRC/dipole physics notes and profile rendering."""

from __future__ import annotations

import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
INDEX = os.path.join(ROOT, "app", "index.html")


def test_frc_profile_uses_backend_rigid_rotor_parameter_not_gaussian_proxy():
    src = open(INDEX, encoding="utf-8").read()
    assert "LASTRUN.outputs.K_rr" in src
    assert "1/Math.pow(Math.cosh(K*(2*rho*rho-1)),2)" in src
    assert "TT.push(1)" in src
    assert "Math.exp(-Math.pow((rho-x0)/w,2))" not in src


def test_frontend_states_frc_fit_and_dipole_coordinate_and_wall_limits():
    src = open(INDEX, encoding="utf-8").read()
    assert "BORAY/Solovev fpsi 等值线" in src
    assert "BORAY/Solovev fpsi contours" in src
    assert 'data-frc-view="half"' in src
    assert 'data-frc-view="full"' in src
    assert "const frcPsiNorm=(z,r)" in src
    assert "const frcSolPsiNorm=(z,r)" in src
    assert "const frcPsiGrid=(sol=false,sgn=1)" in src
    assert "const frcShapeFactor=()=>Math.min(1,Math.max(2/3,+(v.f_shape==null?0.85:v.f_shape)))" in src
    assert "const sepMode=(v.sep_model==='mrr'||v.sep_model==='ma_xie')?'ma_xie':'superellipse'" in src
    assert "const psiNearNull=0.02,psiMax=0.98,psiStep=0.07,solStart=1.16,solEnd=1.72,solStep=0.28" in src
    assert "type:'contour'" in src
    assert "const cs=sol?{start:solStart,end:solEnd,size:solStep}:{start:start??psiStep,end:end??psiMax,size:size??psiStep}" in src
    assert "const addFrcFluxContours=sgn=>{add(frcPsiContour(false,sgn,psiNearNull,psiNearNull,1),'flux');add(frcPsiContour(false,sgn),'flux');}" in src
    assert "const bExtY=Math.max(v.r_s*1.18,v.r_s+0.62*Math.max(0,v.r_w-v.r_s))" in src
    assert "add(seg(bExtZ0,bExtY,bExtZ1,bExtY" in src
    assert "add(seg(bExtZ0,-bExtY,bExtZ1,-bExtY" in src
    assert "colorscale:[[0,c],[1,c]]" in src
    assert "addFrcFluxContours(1);addFrcFluxContours(-1)" in src
    assert "add(frcPsiContour(true,1),'open');add(frcPsiContour(true,-1),'open')" in src
    assert "const rn=v.r_s/Math.SQRT2" in src
    assert "Full FRC cross-section" in src
    assert "ρ<sub>U</sub>=ln(U/U<sub>in</sub>)/ln(U<sub>out</sub>/U<sub>in</sub>)" in src
    assert "球形面积代理" in src
    assert "spherical-area proxy" in src


def test_dipole_frontend_consumes_backend_geometry_instead_of_always_drawing_point_dipole():
    src = open(INDEX, encoding="utf-8").read()
    assert "LASTRUN.shape.type==='dipole'" in src
    assert "sh.surfaces.forEach" in src


def test_dipole_field_input_is_labeled_as_dipole_equivalent_scale():
    src = open(INDEX, encoding="utf-8").read()
    assert "点偶极等效场标度" in src
    assert "dipole-equivalent field scale" in src
    assert "环表面场" not in src
