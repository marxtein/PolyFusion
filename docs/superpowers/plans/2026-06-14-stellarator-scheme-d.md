# Stellarator Scheme D + Presets-as-Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make near-axis the single stellarator geometry (delete legacy rotating-ellipse + `kappa_s`), drive shaping by `etabar` with elongation as a derived output, support custom axis (`rc`/`zs`) and measured-machine overrides (`iota`/`Vp`/`Sw`), rebaseline presets (real machines anchored to real data); and move all presets from Python into JSON with a UI "save my preset" path.

**Architecture:** One geometry engine = `nearaxis.solve_near_axis`. `solve_stellarator` resolves each geometry quantity by priority: explicit override > near-axis computed. Legacy closed-form (`iota_rotating_ellipse`, rotating-ellipse metrics, fourier-display cartoon) is deleted. Presets become per-config JSON files loaded by a small loader; the existing `base.py` `setdefault` post-processing is preserved.

**Tech Stack:** Python 3.11 + numpy (no scipy); stdlib `json`; vanilla JS + Plotly front-end; tests are plain `python -m` scripts (no pytest framework — each test file has a `main()` returning exit code).

---

## Design review (the「审」) — read before executing

### Decisions locked (from this session's discussion)
1. **D1** = near-axis is the analytic engine; **measured-iota fallback** for machines it can't represent (W7-X quasi-isodynamic, LHD heliotron with planar axis).
2. **Delete `kappa_s`** entirely. `etabar` is the single shaping knob. Elongation (`kappa_eff`/`elong_max`) is a **derived output**.
3. **Rebaseline**: accept near-axis volumes for concept reactors; **anchor real machines to real machine data** via `Vp`/`Sw`/`iota` overrides — never tune params to reproduce old legacy numbers.
4. Add **custom axis** `rc`/`zs` and **`Vp`/`Sw` measured overrides** (Scheme D scope = stellarator only).
5. **Presets → JSON** + UI "save my preset" (localStorage). Independent subsystem.

### Geometry resolution order (the core new logic in `solve_stellarator`)
```
a = R0/A
axis = (rc, zs) if rc given     else ([R0, delta_h], [0.0, -delta_h])
near-axis = solve_near_axis(axis, N_fp, etabar)        # etabar > 0 REQUIRED
iota_used = iota_override   if iota_override > 0   else near_axis.iota   (geom)
Vp        = Vp_override     if Vp_override   > 0   else pi*a^2 * L_ax     (Pappus)
Sw        = Sw_override     if Sw_override   > 0   else per_w * L_ax
iota_geom is ALWAYS reported (diagnostic) even when overridden
guard: if iota_used <= _IOTA_MIN -> error "give iota override"  (ISS04 needs iota>0)
```
Key: **volume never needs near-axis to converge** (`axis_length` works for planar axis = 2πR0); near-axis is needed for `iota_geom` + elongation (Sw perimeter). A planar real machine (LHD, delta_h=0) supplies `iota` override; near-axis still runs for elongation (curvature = 1/R0 ≠ 0).

### Blast radius of deleting `kappa_s` (6 files — verified by grep)
- `polyfusion/configs/stellarator.py` — `iota_rotating_ellipse()`, legacy branch in `stellarator_geometry_metrics()`, `section_outlines()` fourier-display, `_check_inputs`, `StellaratorResult.kappa_s`, solver signature.
- `polyfusion/configs/base.py` — `_STELL_PARAMS`, `positive`, `STELL_PRESETS`.
- `app/index.html` — `META.kappa_s`, `RANGES.kappa_s`, `PR.kappa_s`, RGRP whitelist.
- `polyfusion/tests/test_stellarator_sanity.py` — BASE dict + test #2 (`kappa_s up -> iota up`).
- `polyfusion/tests/test_stellarator_benchmark.py` — 4-device anchors keyed on `kappa_s`.
- `polyfusion/tests/test_validation.py` — stellarator `kappa_s=1 -> error` case.

### Tests that WILL break and must be rewritten (not deleted)
- `test_stellarator_sanity.py`: replace `kappa_s` with `etabar`; test #2 becomes "etabar up -> elongation up" and add "delta_h up -> iota up" (torsion). #3 (iota override) stays. #4 (helical axis) stays.
- `test_stellarator_benchmark.py`: real-device iota anchors move to "measured mode" (iota override is the input now); keep them as regression of the closure, not of geometric iota.
- `test_validation.py`: replace `kappa_s=1 -> error` with `etabar<=0 -> error`.
- `test_nearaxis_benchmark.py`: **must stay green untouched** (validates the engine vs pyQSC).
- `test_golden.py`, mirror/frc/dipole tests: unaffected (no stellarator dependency).

### Risks / preconditions
- **Dirty tree on `main`**: pre-existing uncommitted changes (base.py/frc.py/stellarator.py/tests + this session's index.html). MUST branch + checkpoint first (Task A0).
- **`docs/` and `tmp/` are gitignored** but existing docs are force-added. This plan + new docs need `git add -f` to be tracked.
- **Preset volumes for real machines** need literature values (Task A7). Best-estimate starting points: W7-X V≈30 m³, LHD V≈30 m³, HSX V≈0.4 m³, CFQS V≈1 m³, HELIAS V≈1400 m³ (concept, computed — no override). Confirm during execution.
- **No pytest**: run tests via `python polyfusion/tests/test_X.py` (each returns exit 0/1). A runner one-liner is in Task A-final.

### Scope split (per writing-plans scope check)
- **Plan A** (Tasks A0–A11): stellarator geometry rewrite. Physics-critical, self-contained, agreed Scheme D. Execute first.
- **Plan B** (Tasks B0–B6): presets→JSON + UI authoring. Independent, touches all configs. Execute after A (or in parallel by a separate worker).

---

# PLAN A — Stellarator geometry (Scheme D)

### Task A0: Branch + checkpoint the dirty tree

**Files:** none (git only)

- [ ] **Step 1: Confirm current state**

Run: `git -C E:/work/digitalfusion-release status --short && git -C E:/work/digitalfusion-release branch --show-current`
Expected: `main`, with M on app/index.html, base.py, frc.py, stellarator.py, tests.

- [ ] **Step 2: Commit existing work as a checkpoint** (ASK USER before committing — confirm the dirty changes are wanted)

```bash
git -C E:/work/digitalfusion-release add -A
git -C E:/work/digitalfusion-release commit -m "checkpoint: pre-Scheme-D working tree (UI layer-unify + prior physics edits)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 3: Create the feature branch**

```bash
git -C E:/work/digitalfusion-release checkout -b scheme-d-stellarator
```
Expected: "Switched to a new branch 'scheme-d-stellarator'".

---

### Task A1: Anti-dead-param regression test (TDD guard — write FIRST, must fail meaningfully)

**Files:**
- Create: `polyfusion/tests/test_stellarator_param_activity.py`

This test encodes the whole point of Scheme D: every exposed geometry param must move an output. It is written before the refactor and becomes the green-gate.

- [ ] **Step 1: Write the failing test**

```python
"""Every stellarator geometry parameter must change at least one core output.
Guards against the Scheme-D motivating bug (kappa_s dead in near-axis,
delta_h dead for iota in legacy).  Run: python polyfusion/tests/test_stellarator_param_activity.py
"""
import inspect, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from polyfusion.configs.stellarator import solve_stellarator

ACCEPTED = set(inspect.signature(solve_stellarator).parameters)
# post-Scheme-D base: near-axis, etabar-driven, NO kappa_s
BASE = dict(R0=18.0, A=10.0, N_fp=5, delta_h=0.9, etabar=0.05, Sn=0.5, ST=1.0,
            ni0=2e20, Ti0=15.0, fT=1.0, fsig=1.0, f1=0.5, B0=5.0, tauE=1.0,
            fHe=0.04, fimp=0.01, Zimp=10, Rw=0.7, g=0.1, icase=1)
# param -> at least one output key it must move (+20% bump, or set for sentinels)
EXPECT = {
    "R0":      ["Vp"], "A": ["Vp"], "N_fp": ["iota_geom"], "delta_h": ["iota_geom"],
    "etabar":  ["elong_max"], "g": ["Sw"], "B0": ["betaT"],
}

def _run(p): return solve_stellarator(**{k: v for k, v in p.items() if k in ACCEPTED}).as_dict()

def main():
    assert "kappa_s" not in ACCEPTED, "kappa_s must be removed from the solver"
    r0 = _run(BASE); ok = True
    for p, keys in EXPECT.items():
        q = dict(BASE); q[p] = BASE[p] * 1.2
        r = _run(q)
        moved = any(abs(r[k]-r0[k])/(abs(r0[k])+1e-30) > 1e-6 for k in keys)
        print(("PASS" if moved else "FAIL"), f"{p} moves {keys}")
        ok &= moved
    print("\nRESULT:", "ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it — expect failure now**

Run: `cd /e/work/digitalfusion-release && PYTHONPATH=. python polyfusion/tests/test_stellarator_param_activity.py`
Expected: FAIL — current solver still accepts `kappa_s` (assert trips) and/or rejects `etabar`-only base. This is the red state Scheme D must turn green.

---

### Task A2: Rewrite `solve_stellarator` — single near-axis path, delete legacy, add overrides

**Files:**
- Modify: `polyfusion/configs/stellarator.py`

- [ ] **Step 1: Delete legacy geometry**
Remove `iota_rotating_ellipse()` and `axis_length()`-only legacy paths' use; in `stellarator_geometry_metrics()` delete the `else` (etabar==0) branch — keep only the near-axis branch. `axis_length()` stays (used for `L_ax` of the axis incl. planar). `_ellipse_perimeter` stays (perimeter from near-axis elongation profile).

- [ ] **Step 2: New solver signature**
Replace `kappa_s` with `etabar` (required, validated >0); add `rc=None, zs=None, Vp_override=0.0, Sw_override=0.0`. Remove `kappa_s` from `StellaratorResult` (replace echo field with `etabar` already present). Update `_check_inputs`: drop `kappa_s>0`; add `etabar != 0` required; keep `delta_h>=0`, `N_fp>=1`.

- [ ] **Step 3: Resolution-order block** (replaces lines ~401–424 geometry section)

```python
    a = R0 / A
    axis_rc = list(rc) if rc is not None else [R0, delta_h]
    axis_zs = list(zs) if zs is not None else [0.0, -delta_h]
    geom = stellarator_geometry_metrics(R0, A, N_fp, axis_rc, axis_zs, etabar, g)
    L_ax = geom["L_ax"]; iota_geom = geom["iota_geom"]
    helicity = geom["helicity"]; kappa_eff = geom["kappa_eff"]; elong_max = geom["elong_max"]
    Vp = Vp_override if Vp_override and Vp_override > 0 else geom["Vp_geom"]
    Sp = geom["Sp_geom"]
    Sw = Sw_override if Sw_override and Sw_override > 0 else geom["Sw_geom"]
    iota_used = iota if (iota is not None and iota > 0) else iota_geom
    if iota_used <= _IOTA_MIN:
        raise ValueError("rotational transform is ~0: give an explicit iota "
                         "override (measured machine) or a shaping that produces "
                         "transform (etabar + helical/multi-harmonic axis)")
```
`stellarator_geometry_metrics` is refactored to take `(R0, A, N_fp, rc, zs, etabar, g)` and always call `solve_near_axis(rc, zs, N_fp, etabar)`.

- [ ] **Step 4: Run param-activity test**
Run: `cd /e/work/digitalfusion-release && PYTHONPATH=. python polyfusion/tests/test_stellarator_param_activity.py`
Expected: PASS (kappa_s gone; etabar moves elong_max; delta_h moves iota_geom; Vp from R0/A).

- [ ] **Step 5: Commit**
```bash
git add polyfusion/configs/stellarator.py polyfusion/tests/test_stellarator_param_activity.py
git commit -m "feat(stellarator): single near-axis geometry; delete kappa_s/legacy; add iota/Vp/Sw overrides + custom axis"
```

---

### Task A3: `section_outlines` — real near-axis sections + wall layer, delete cartoon

**Files:**
- Modify: `polyfusion/configs/stellarator.py` (`section_outlines`)

- [ ] **Step 1:** Delete the legacy `display`-dict fourier-display branch. Always produce near-axis first-order surfaces (the existing `etabar` branch). Accept `rc`/`zs` if given.
- [ ] **Step 2:** Add a `wall` outline per section: offset the boundary normal-outward by `g` (reuse the elongation-profile perimeter logic: wall ellipse semi-axes `a√e + g`, `a/√e + g`). Return `{"sections":[{...,"wall":{"R":[...],"Z":[...]}}], ...}`.
- [ ] **Step 3:** Sanity-run shape: `PYTHONPATH=. python -c "from polyfusion.configs.stellarator import section_outlines as s; d=s(R0=18,A=10,N_fp=3,delta_h=0.81,etabar=0.05,g=0.1); print(d['mode'], len(d['sections']), 'wall' in d['sections'][0])"`
Expected: `near-axis 3 True`.
- [ ] **Step 4: Commit** `git commit -am "feat(stellarator): near-axis section outlines with wall layer (g visible); drop cartoon"`

---

### Task A4: Update `base.py` STELL ConfigSpec (params, bounds, positive)

**Files:**
- Modify: `polyfusion/configs/base.py`

- [ ] **Step 1:** `_STELL_PARAMS`: remove `kappa_s`; add `rc`, `zs`, `Vp_override`, `Sw_override`. Keep `etabar`.
- [ ] **Step 2:** `STELLARATOR.positive`: drop `kappa_s`. `required`: ensure `etabar` required, `rc`/`zs`/`Vp_override`/`Sw_override`/`iota` optional.
- [ ] **Step 3:** `bounds`: add `etabar:(0,None)` is wrong (etabar can be negative sign-irrelevant; keep `etabar` unbounded but `_stell_cross` requires `!=0`); add `Vp_override:(0,None)`, `Sw_override:(0,None)`. `_stell_cross`: require `etabar` present & `!=0`; keep iota>0-if-given.
- [ ] **Step 4: Commit** `git commit -am "feat(stellarator): ConfigSpec params for etabar/rc/zs/Vp_override/Sw_override; drop kappa_s"`

---

### Task A5: Rewrite `test_stellarator_sanity.py`

**Files:**
- Modify: `polyfusion/tests/test_stellarator_sanity.py`

- [ ] **Step 1:** BASE → near-axis (replace `kappa_s=2.7` with `etabar=0.05`). Replace test #2 with:
```python
    sh = solve_stellarator(**{**BASE, "etabar": 0.07})
    allok &= _ok(sh.elong_max > r.elong_max, "etabar up -> elongation up")
    dh = solve_stellarator(**{**BASE, "delta_h": 1.2})
    allok &= _ok(dh.iota_geom != r.iota_geom, "delta_h changes iota (torsion)")
```
Keep #3 (iota override), #4 (helical L_ax/Vp), #5–7.
- [ ] **Step 2: Run** `PYTHONPATH=. python polyfusion/tests/test_stellarator_sanity.py` → Expected: ALL PASS.
- [ ] **Step 3: Commit** `git commit -am "test(stellarator): sanity uses etabar; etabar->elong, delta_h->iota"`

---

### Task A6: Measured-override tests (new behavior coverage)

**Files:**
- Modify: `polyfusion/tests/test_stellarator_param_activity.py` (append override asserts) OR new `test_stellarator_overrides.py`

- [ ] **Step 1:** Assert: `Vp_override=50` → `Vp==50` and `Pfus` scales ∝ override; `Sw_override=200` → `Sw==200`; planar axis `delta_h=0` + `iota=0.4` override runs without error and `iota==0.4`; custom `rc=[18,0.9,0.1]` differs from single-harmonic `Vp`/`iota`.
- [ ] **Step 2: Run → PASS. Step 3: Commit.**

---

### Task A7: Rebaseline presets (concept = computed; real machine = measured override)

**Files:**
- Modify: `polyfusion/configs/base.py` `STELL_PRESETS` (until Plan B moves them to JSON; if Plan B done first, edit the JSON instead)

- [ ] **Step 1: Gather reference plasma volumes** (literature). Starting values to confirm: W7-X≈30 m³, LHD≈30 m³, HSX≈0.4 m³, CFQS≈1 m³. Source: device design papers / `digitalfusion-compare` refs.
- [ ] **Step 2: Rewrite presets:**
  - HELIAS, NAE-QA: pure near-axis, no override. HELIAS: set `etabar` so `iota_geom`∈[0.8,0.95] (tune; start 0.05), `delta_h=0.9`, `N_fp=5`. Accept computed Vp as new baseline.
  - W7-X: `etabar=0.05, N_fp=5, delta_h=0.25, iota=0.88, Vp_override=30`.
  - LHD: `etabar=0.04, N_fp=10, delta_h=0.0, iota=0.40, Vp_override=30`.
  - HSX: `etabar=0.08, N_fp=4, delta_h=0.1, iota=1.05, Vp_override=0.4`.
  - CFQS: `etabar=0.06, N_fp=2, delta_h=0.05, iota=0.45, Vp_override=1.0`.
  Remove `kappa_s` from all. Keep `f_ren`, plasma/field params.
- [ ] **Step 3:** Update the `STELL_PRESETS` `setdefault` loop (drop `iota=0.0` default if iota now explicit per real machine; keep for concept presets).
- [ ] **Step 4: Run all presets:** `PYTHONPATH=. python -c "from polyfusion.io import run_preset; [print(n, run_preset(n,'stellarator').get('outputs',{}).get('Qfus','ERR'), run_preset(n,'stellarator').get('errors')) for n in ['HELIAS','NAE-QA','W7-X','LHD','HSX','CFQS']]"`
Expected: all run, valid, Q finite, no errors.
- [ ] **Step 5: Commit** `git commit -am "feat(stellarator): rebaseline presets — concepts near-axis, real machines measured-iota+Vp override"`

---

### Task A8: Rewrite stellarator parts of `test_stellarator_benchmark.py` + `test_validation.py`

**Files:**
- Modify: `polyfusion/tests/test_stellarator_benchmark.py`, `polyfusion/tests/test_validation.py`

- [ ] **Step 1:** benchmark: device anchors now feed measured `iota`; assert the **closure** (ISS04 H, Sudo) reproduces, not geometric iota. Keep near-axis §6 (NAE-QA iota_geom=0.4183) as the engine anchor.
- [ ] **Step 2:** validation: replace `kappa_s=1 -> error` with `etabar=0 -> error` and `iota~0 with planar axis & no override -> error`.
- [ ] **Step 3: Run both → PASS. Commit.**

---

### Task A9: UI — stellarator param panel (delete kappa_s, expose etabar/overrides/advanced axis) + wall layer

**Files:**
- Modify: `app/index.html`

- [ ] **Step 1:** `META`: delete `kappa_s`; ensure `etabar` label = "近轴形参 η̄ (塑形)"; add `Vp_override`(`几何:体积实测覆盖 m³ (0=几何算)`), `Sw_override`, and an advanced `rc`/`zs` text field. `RANGES`: delete `kappa_s`; add `etabar:[0.01,0.2]`. `PR`/RGRP whitelist: drop `kappa_s`, ensure `kappa_eff`/`elong_max` shown as derived.
- [ ] **Step 2:** `applyModeLocks`: when `iota>0` (measured), annotate that `etabar`/axis only affect size/elongation, not the transform.
- [ ] **Step 3:** `drawShape` stellarator branch: add the `wall` group from `sh.sections[i].wall` (the layer framework already supports a `wall` group). Remove the "wall pending" note.
- [ ] **Step 4:** Custom axis input: parse comma-separated `rc`/`zs` into arrays in `clean()` before POST (pass through as arrays; server `_floatify` keeps non-numbers as-is — verify lists survive: they hit the `else` branch and pass through).
- [ ] **Step 5: Verify in browser** (preview server `polyfusion`): select stellarator, each preset renders with a wall; bump etabar → section elongation changes; set iota override → readout shows it; no console errors.
- [ ] **Step 6: Commit** `git commit -am "feat(ui): stellarator etabar/overrides/custom-axis panel + wall layer; drop kappa_s"`

---

### Task A10: Docs sync

**Files:**
- Modify: `docs/27_*.md` (stellarator doc) + appendix; note the legacy removal + override semantics + cartoon removal in the audit reports.

- [ ] **Step 1:** Update geometry section: single near-axis path, etabar shaping, measured override semantics, custom axis. **Step 2:** Commit.

---

### Task A11: Full regression + branch wrap

- [ ] **Step 1: Run the whole suite**
```bash
cd /e/work/digitalfusion-release && for t in golden literature mirror_benchmark mirror_sanity frc_benchmark frc_sanity dipole_benchmark dipole_sanity stellarator_benchmark stellarator_sanity stellarator_param_activity nearaxis_benchmark validation release_simplified physics_p1_benchmark physics_p2_benchmark physics_p3_benchmark; do echo "== $t =="; PYTHONPATH=. python polyfusion/tests/test_$t.py >/dev/null 2>&1 && echo PASS || echo FAIL; done
```
Expected: all PASS (golden/mirror/frc/dipole/nearaxis unchanged; stellarator updated).
- [ ] **Step 2:** Browser e2e all 5 configs (preview), no console errors.
- [ ] **Step 3:** Use `superpowers:finishing-a-development-branch` to merge `scheme-d-stellarator` → `main` (ASK USER).

---

# PLAN B — Presets as data (JSON) + UI authoring  (independent; execute after/parallel to A)

### Task B0: Branch
- [ ] `git checkout -b presets-as-data` (off main, after A merged or off A's branch — coordinate).

### Task B1: JSON preset files + loader (TDD)
**Files:**
- Create: `polyfusion/presets/{tokamak,mirror,frc,dipole,stellarator}.json` (each `{"presets":{...}, "groups":{...}}`)
- Create: `polyfusion/presets_io.py` (`load_presets(config) -> (dict, groups)`, reads packaged JSON + optional user dir)
- Create: `polyfusion/tests/test_presets_io.py`

- [ ] **Step 1: Failing test** — assert `load_presets("tokamak")` returns ITER with `Pfus` golden after solve; assert all 5 configs load; assert a user-dir JSON merges and overrides.
- [ ] **Step 2:** Generate JSON from current Python dicts (one-off script reads `presets.PRESETS` / `base.*_PRESETS` and dumps). **Step 3:** Implement loader. **Step 4:** `base.py` + `presets.py` import via loader (keep `setdefault` post-processing). **Step 5:** Run test + full suite (golden must still be 2.67e-4). **Step 6:** Commit.

### Task B2: User preset dir (server-side optional) — read merge only
- [ ] Loader merges `~/.polyfusion/presets/<config>.json` if present (read-only; no server write API in this task). Test merge precedence. Commit.

### Task B3: UI — "save my preset" (localStorage)
**Files:** `app/index.html`
- [ ] Add "另存为预设" button → prompt name → store `{config, name, vals}` in `localStorage["polyfusion_presets"]`; merge into the preset dropdown under an optgroup "我的预设 / My presets"; load applies VALS; add delete. Export/import JSON already exists — wire "import → save as preset".
- [ ] Browser-verify: save EAST-tweaked point as "test1", reload page, "test1" still in dropdown, loads correctly. Commit.

### Task B4: UI — surface custom axis / overrides as "design your own" (stellarator; depends on Plan A)
- [ ] If A merged: ensure rc/zs/Vp/Sw fields are in an "高级/自定义" collapsible. Commit.

### Task B5: Docs
- [ ] Add `docs/` how-to: "加预设 / 喂实测值 / 自定义位形" user guide (the 3-tier model from this session). Commit.

### Task B6: Regression + merge
- [ ] Full suite green; browser e2e; `finishing-a-development-branch` merge (ASK USER).

---

## Self-review (run against the spec)

- **Spec coverage:** D1 ✓(A2 resolution order + measured override) · delete kappa_s ✓(A2/A4/A9 + tests A5/A8) · etabar shaping + derived elongation ✓(A2/A5) · rebaseline real-anchors ✓(A7) · custom axis rc/zs ✓(A2/A6/A9) · Vp/Sw override ✓(A2/A6) · presets→JSON ✓(B1) · UI save preset ✓(B3). All covered.
- **Type consistency:** `stellarator_geometry_metrics(R0,A,N_fp,rc,zs,etabar,g)` signature used identically in A2/A3; `Vp_override`/`Sw_override`/`iota` override naming consistent across solver/ConfigSpec/UI; `solve_near_axis(rc,zs,nfp,etabar)` matches existing `nearaxis.py`.
- **Research dependency (not a placeholder):** A7 Step 1 = literature volumes, with starting values + sources given.
- **Ordering risk:** A7 edits `STELL_PRESETS` in base.py; if Plan B runs first, edit the JSON instead (noted in A7 Files line).
