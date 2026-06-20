# 进度日志

## 2026-06-20

- **checkpoint 1** — P0 侦察完成。
  - 摸清平衡机制(manifest+server)、veqpy 数据源、index.html 全部 UI 锚点行号。
  - 写 task_plan.md / findings.md。
  - 下一步：P1 联网调研(RESEARCH) + 并行启动 EQ、PRESET/PHYS agent。

- **checkpoint 2** — 并行 agent 两个完成 + index.html 主改完成。
  - RESEARCH agent ✅：research_notes.md。结论：仿星器有 H 模(W7-AS/HDH)，但只弱密度台基、无温度台基；托卡马克 n、T 双台基(宽~4%a, top 0.3-0.6)。mirror/frc/dipole 判据缺漏已列(见 T7)。
  - PRESET agent ✅：5 个 json 各加 `用户设计 User Design` + `自定义 Custom` 组，全部 load+run valid (T9 done)。
  - 我改 index.html：T3 去导入弹窗 ✅；T4 传统→双椭圆(label+meta) ✅；T5 颜色统一(GEO flux→灰、wall→红；仿星器边界→青) ✅；T8 H 模剖面(托卡马克双台基/仿星器弱密度台基无 T 台基) ✅。
  - 改 test_presets_io.py：EXPECTED_GROUPS 加 `自定义 Custom`。
  - EQ agent 仍在跑(平衡文件下载)。
  - ⚠ 发现：test_presets_io.py 的 ITER Pfus golden=381.39 但实际 433.55（上个提交改了 ITER 参数，golden 未更新）→ 预存 bug，QA 阶段处理。
  - 待办：T6 几何参数标注(等 EQ 完成后串行改 index.html)、T7 best_window 物理改进(base.py)、QA。

- **checkpoint 3** (commit bb65106) — T1/T2 平衡文件 + T7 FRC 倾斜门 + 测试修复。全量 pytest 98 通过/2 预存失败。

- **checkpoint final** — T6 几何参数标注完成 + 浏览器验收通过。
  - T6 各位形标注(浏览器 eval 实测)：托卡马克 a/κa/δ；磁镜 L_c/a_c/R_m+损失锥公式；FRC r_s/l_s/r_w/E+s/E；偶极 r_ring+交换稳定公式；仿星器 R0/a/N_fp/ι(meta)。
  - 验收：5 位形几何图颜色统一(青边界/红壁/灰磁面)实测通过；控制台零错误；T8 剖面实测(托卡马克双台基 n 1→0.12、仿星器弱密度台基 n→0.36 且 T 无台基→0)；node 语法检查 OK；mirror 几何截图无重叠。
  - 预存失败(非本次)：solve_mirror multi_zone kwarg；normalizeStellBoundaryIota 缺失；ITER Pfus golden 漂移(433.55 vs 381.39)。
