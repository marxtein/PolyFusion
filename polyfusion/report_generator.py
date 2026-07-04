"""One-click simulation report generator for PolyFusion.

Renders a self-contained HTML report from a snapshot of the current UI
state (operating point, POPCON scan, embedded Plotly PNGs). HTML rendering
uses the Python standard library only: no Jinja, no server-side PDF. The
user prints-to-PDF from the browser.

The HTML escapes every user-supplied field so a malicious parameter
value cannot inject markup. Image payloads must be valid
``data:image/png;base64,...`` URIs produced client-side by Plotly.toImage;
anything else is silently dropped.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Iterable


_REPORT_CSS = """
body{font-family:system-ui,"Microsoft YaHei","PingFang SC",sans-serif;
  color:#1a2332;background:#f7f9fc;margin:0;line-height:1.55;
  font-size:13px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.wrap{max-width:1040px;margin:0 auto;padding:32px 40px}
h1{font-size:22px;margin:0 0 4px;color:#0c3a5e}
h2{font-size:15px;color:#0c8678;border-bottom:1px solid #c3cddc;
  padding-bottom:4px;margin:28px 0 10px}
.sub{color:#51607a;font-size:12px;margin-bottom:4px}
.meta{display:flex;flex-wrap:wrap;gap:6px 24px;font-size:12px;color:#49586f;
  margin:10px 0 0;padding:10px 14px;background:#fff;border:1px solid #e0e5ee;border-radius:6px}
.meta b{color:#1a2332}
.actions{margin:14px 0 4px;text-align:right}
.actions button{border:1px solid #c3cddc;background:#fff;color:#0c3a5e;border-radius:5px;
  padding:6px 10px;cursor:pointer;font-size:12px;margin-left:6px}
.actions button:hover{border-color:#0c8678;color:#0c8678}
.actions .status{display:inline-block;margin-left:8px;color:#8995a8;font-size:12px}
table{width:100%;border-collapse:collapse;margin:6px 0 14px;background:#fff}
th,td{padding:5px 9px;border-bottom:1px solid #e6ebf2;text-align:left;font-size:12px}
th{background:#f0f4f9;color:#0c3a5e;font-weight:600}
td.k{font-family:"JetBrains Mono",monospace;color:#49586f;white-space:nowrap;width:38%}
td.u{color:#8995a8;font-family:monospace;width:8%}
tr.hl td{background:#fff7e8;font-weight:700}
.imgbox{margin:8px 0 16px;text-align:center}
.imgbox img{max-width:100%;border:1px solid #e0e5ee;border-radius:4px;background:#fff}
.imgbox .cap{font-size:11px;color:#51607a;margin-top:4px}
.note{background:#fff7e8;border-left:3px solid #ffb02e;padding:8px 12px;
  margin:8px 0;font-size:12px;color:#5a4a1c;border-radius:0 4px 4px 0}
.empty{color:#8995a8;font-style:italic;padding:6px 0}
.errlist{background:#fff0f1;border-left:3px solid #cc3a50;padding:8px 12px;
  border-radius:0 4px 4px 0;font-family:monospace;font-size:11.5px;color:#7a1f2c}
.part-title{font-size:17px;border-bottom:2px solid #0c8678;margin-top:32px}
.ai-report{background:#fff;border:1px solid #e0e5ee;border-radius:6px;padding:12px 14px;
  font-size:12.5px;color:#1a2332}
.ai-report.loading{color:#8995a8;font-style:italic;white-space:pre-wrap}
.ai-report.error{background:#fff0f1;border-color:#f0c5cc;color:#7a1f2c;white-space:pre-wrap}
.ai-report h1,.ai-report h2,.ai-report h3{border:0;margin:10px 0 6px;padding:0;color:#0c3a5e}
.ai-report h1{font-size:16px}.ai-report h2{font-size:14px}.ai-report h3{font-size:13px}
.ai-report p{margin:6px 0}.ai-report ul,.ai-report ol{margin:6px 0 8px 22px;padding:0}
.ai-report li{margin:3px 0}.ai-report pre{background:#f0f4f9;border:1px solid #e0e5ee;
  border-radius:4px;padding:8px;overflow:auto;white-space:pre-wrap}
.ai-report code{font-family:"JetBrains Mono",monospace;background:#f0f4f9;border-radius:3px;padding:0 3px}
@media print{.actions{display:none}.wrap{padding:8px 0}h2{page-break-after:avoid}
  .imgbox{page-break-inside:avoid}}
"""


def _version() -> str:
    """Best-effort version stamp for the report footer.

    Order: ``POLYFUSION_VERSION`` env var → short git commit hash →
    ``"unknown"``. Failures (no git, no permission) fall through silently.
    """
    env = os.environ.get("POLYFUSION_VERSION")
    if env:
        return env.strip()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    for _ in range(3):
        try:
            out = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=repo,
                    stderr=subprocess.DEVNULL,
                    timeout=2.0,
                )
                .decode()
                .strip()
            )
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
        repo = os.path.dirname(repo)
    return "unknown"


def _esc(x: Any) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def _fmt(x: Any, nd: int = 3) -> str:
    """Format a numeric value compactly; pass through strings/None."""
    if x is None:
        return ""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, (int, float)):
        if isinstance(x, float) and (x != x or x in (float("inf"), float("-inf"))):
            return "—"
        if abs(x) >= 1e5 or (abs(x) < 1e-3 and x != 0):
            return f"{x:.3e}"
        if isinstance(x, int):
            return str(x)
        return f"{x:.{nd}g}"
    return _esc(x)


def _kv_table(rows: Iterable[tuple[str, Any, str]]) -> str:
    out = ["<table>"]
    for k, v, u in rows:
        out.append(
            f"<tr><td class='k'>{_esc(k)}</td><td>{_fmt(v)}</td><td class='u'>{_esc(u)}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _mean_2d(grid: list[list[Any]]) -> float:
    """Compute the mean of a rectangular 2-D numeric grid using stdlib only."""
    total = 0.0
    count = 0
    for row in grid:
        for v in row:
            if isinstance(v, (int, float)):
                total += float(v)
                count += 1
    return total / count if count else float("nan")


def _summary_text(last_run: dict | None, last_scan: dict | None) -> str:
    """Auto-generated one-line conclusion based on the operating window."""
    if not last_run:
        return "未运行工作点计算 / No operating-point result available."
    outs = last_run.get("outputs") or {}
    pfus = outs.get("Pfus")
    q = outs.get("Qfus")
    pwall = outs.get("Pwall")
    parts: list[str] = []
    if pfus is not None:
        parts.append(f"P_fus={_fmt(pfus)} MW")
    if q is not None:
        parts.append(f"Q={_fmt(q)}")
    if pwall is not None:
        parts.append(f"P_wall={_fmt(pwall)} MW/m²")
    head = "工作点 / Operating point: " + (" · ".join(parts) if parts else "无关键指标")
    if last_scan and "best" in last_scan:
        try:
            area_frac = _mean_2d(last_scan["best"])
        except (TypeError, ValueError):
            area_frac = float("nan")
        if area_frac == area_frac:
            head += f" | 最佳区占扫描网格 {area_frac * 100:.1f}%"
        n_inv = last_scan.get("n_invalid")
        if n_inv:
            head += f" | {n_inv} 个扫描点物理无效"
    return head


def _params_rows(params: dict) -> list[tuple[str, Any, str]]:
    """Pick the most informative params and order them stably.

    Keeps the report compact: only scalar numerics/strings; drops internal
    flags prefixed with ``_`` and dense arrays.
    """
    if not isinstance(params, dict):
        return []
    out = []
    for k, v in params.items():
        if isinstance(k, str) and k.startswith("_"):
            continue
        if isinstance(v, (list, tuple, dict)):
            continue
        out.append((str(k), v, ""))
    return out


def _outputs_rows(last_run: dict | None) -> list[tuple[str, Any, str]]:
    if not last_run:
        return []
    return [(str(k), v, "") for k, v in (last_run.get("outputs") or {}).items()]


_HIGHLIGHT_KEYS = {"Pfus", "Qfus", "Pwall", "betaN", "H98", "tau_E"}


def _outputs_table(rows: list[tuple[str, Any, str]]) -> str:
    if not rows:
        return '<div class="empty">无输出 / no outputs</div>'
    out = ["<table>"]
    for k, v, u in rows:
        hl = ' class="hl"' if k in _HIGHLIGHT_KEYS else ""
        out.append(
            f"<tr{hl}><td class='k'>{_esc(k)}</td><td>{_fmt(v)}</td><td class='u'>{_esc(u)}</td></tr>"
        )
    out.append("</table>")
    return "".join(out)


def _errors_block(last_run: dict | None) -> str:
    if not last_run:
        return ""
    errs = last_run.get("errors") or []
    if not errs:
        return ""
    items = "".join(f"<li>{_esc(e)}</li>" for e in errs)
    return f'<div class="errlist"><b>求解器警告 / Solver warnings:</b><ul>{items}</ul></div>'


def _scan_block(last_scan: dict | None) -> str:
    if not last_scan:
        return '<div class="empty">未运行 POPCON 扫描 / no scan run</div>'
    rows = [
        ("xkey", last_scan.get("xkey"), ""),
        ("ykey", last_scan.get("ykey"), ""),
        ("nx", len(last_scan.get("x") or []), ""),
        ("ny", len(last_scan.get("y") or []), ""),
        ("n_invalid", last_scan.get("n_invalid", 0), ""),
    ]
    return _kv_table(rows)


_DATA_IMAGE_PNG_RE = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")


def _image_block(images: dict, key: str, caption_zh: str, caption_en: str) -> str:
    src = (images or {}).get(key)
    if not src:
        return ""
    if not _DATA_IMAGE_PNG_RE.match(src):
        return ""
    return (
        f'<div class="imgbox"><img src="{_esc(src)}" alt="{_esc(caption_en)}">'
        f'<div class="cap">{_esc(caption_zh)} / {_esc(caption_en)}</div></div>'
    )


def _md_fmt(x: Any) -> str:
    rendered = _fmt(x)
    return rendered.replace("|", "\\|").replace("\n", " ")


def _md_table(rows: list[tuple[str, Any, str]]) -> str:
    if not rows:
        return "无 / none"
    out = ["| 项目 / Item | 值 / Value | 单位 / Unit |", "|---|---:|---|"]
    for key, value, unit in rows:
        out.append(f"| {_md_fmt(key)} | {_md_fmt(value)} | {_md_fmt(unit)} |")
    return "\n".join(out)


def _report_markdown(
    *,
    title: str,
    config: Any,
    config_label: Any,
    preset: Any,
    user: Any,
    ts: Any,
    version: Any,
    summary: str,
    output_rows: list[tuple[str, Any, str]],
    param_rows: list[tuple[str, Any, str]],
    scan_rows: list[tuple[str, Any, str]],
    image_keys: list[str],
    disclaimer: str,
    is_zh: bool,
) -> str:
    lines = [
        f"# {_md_fmt(title)}",
        "",
        f"- 位形 / Config: {_md_fmt(config_label)}",
        f"- 预设 / Preset: {_md_fmt(preset)}",
        f"- 用户 / User: {_md_fmt(user)}",
        f"- 时间 / Time: {_md_fmt(ts)}",
        f"- 版本 / Version: {_md_fmt(version)}",
        f"- Key: {_md_fmt(config)}",
        "",
        "## 基础报告" if is_zh else "## Basic Report",
        "",
        "### 一、结论摘要" if is_zh else "### 1. Summary",
        "",
        _md_fmt(summary),
        "",
        "### 二、工作点输出" if is_zh else "### 2. Operating-point outputs",
        "",
        _md_table(output_rows),
        "",
        "### 三、输入参数" if is_zh else "### 3. Input parameters",
        "",
        _md_table(param_rows),
        "",
        "### 四、POPCON 扫描摘要" if is_zh else "### 4. POPCON scan summary",
        "",
        _md_table(scan_rows),
        "",
        "### 五、图表" if is_zh else "### 5. Figures",
        "",
    ]
    if image_keys:
        labels = {"popcon": "POPCON", "shape": "Geometry", "profile": "Profiles"}
        lines.extend(f"- {labels.get(key, key)}" for key in image_keys)
    else:
        lines.append("无图表 / no figures")
    lines.extend(
        [
            "",
            "### 六、注意事项" if is_zh else "### 6. Notes",
            "",
            _md_fmt(disclaimer),
            "",
            "## AI 分析报告" if is_zh else "## AI Analysis Report",
            "",
            "加载中…" if is_zh else "Loading…",
            "",
        ]
    )
    return "\n".join(lines)


def _report_script(markdown_doc: str, filename: str) -> str:
    markdown_json = json.dumps(markdown_doc, ensure_ascii=False)
    filename_json = json.dumps(filename, ensure_ascii=False)
    return rf"""
<script>
(function(){{
  const baseMarkdown={markdown_json};
  const filename={filename_json};
  window.POLYFUSION_REPORT_MARKDOWN=baseMarkdown;
  function escapeHtml(s){{return String(s||'').replace(/[&<>\"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]));}}
  function inline(s){{return escapeHtml(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');}}
  function renderMarkdown(md){{
    const lines=String(md||'').replace(/\r\n/g,'\n').split('\n');
    const out=[];let list=null;let inCode=false;let code=[];
    function closeList(){{if(list){{out.push('</'+list+'>');list=null;}}}}
    for(const raw of lines){{
      const line=raw.trimEnd();
      if(line.trim().startsWith('```')){{
        if(inCode){{out.push('<pre><code>'+escapeHtml(code.join('\n'))+'</code></pre>');code=[];inCode=false;}}
        else{{closeList();inCode=true;code=[];}}
        continue;
      }}
      if(inCode){{code.push(raw);continue;}}
      if(!line.trim()){{closeList();continue;}}
      let m=line.match(/^(#{1, 3})\s+(.+)$/);
      if(m){{closeList();out.push('<h'+m[1].length+'>'+inline(m[2])+'</h'+m[1].length+'>');continue;}}
      m=line.match(/^[-*]\s+(.+)$/);
      if(m){{if(list!=='ul'){{closeList();out.push('<ul>');list='ul';}}out.push('<li>'+inline(m[1])+'</li>');continue;}}
      m=line.match(/^\d+[.)]\s+(.+)$/);
      if(m){{if(list!=='ol'){{closeList();out.push('<ol>');list='ol';}}out.push('<li>'+inline(m[1])+'</li>');continue;}}
      closeList();out.push('<p>'+inline(line.trim())+'</p>');
    }}
    if(inCode)out.push('<pre><code>'+escapeHtml(code.join('\n'))+'</code></pre>');
    closeList();
    return out.join('');
  }}
  window.POLYFUSION_SET_AI_REPORT=function(text,isError){{
    const box=document.getElementById('aiReport');if(!box)return;
    const content=String(text||'');
    if(isError){{box.className='ai-report error';box.textContent=content;return;}}
    box.className='ai-report';box.innerHTML=renderMarkdown(content);
    const aiTitle=baseMarkdown.includes('## AI 分析报告')?'## AI 分析报告':'## AI Analysis Report';
    const aiStart=baseMarkdown.indexOf(aiTitle);
    window.POLYFUSION_REPORT_MARKDOWN=(aiStart>=0?baseMarkdown.slice(0,aiStart):baseMarkdown+'\n\n')+aiTitle+'\n\n'+content+'\n';
  }};
  const btn=document.getElementById('exportMarkdown');
  if(btn)btn.onclick=function(){{
    const blob=new Blob([window.POLYFUSION_REPORT_MARKDOWN||baseMarkdown],{{type:'text/markdown;charset=utf-8'}});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=filename;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(a.href);
  }};
  const saveBtn=document.getElementById('saveReport');
  if(saveBtn)saveBtn.onclick=function(){{
    const status=document.getElementById('saveReportStatus');
    if(typeof window.POLYFUSION_SAVE_REPORT==='function'){{
      if(status)status.textContent='保存中… / Saving…';
      window.POLYFUSION_SAVE_REPORT();
    }}else if(status){{status.textContent='请在 PolyFusion 登录后保存 / Sign in from PolyFusion to save';status.style.color='#7a1f2c';}}
  }};
}})();
</script>
"""


def generate_report(data: dict) -> str:
    """Render a self-contained HTML report.

    ``data`` schema (all keys optional unless noted):

    - ``config`` (str): configuration key (tokamak/mirror/…)
    - ``config_label`` (str): human-readable configuration name
    - ``preset`` (str): preset name
    - ``params`` (dict): parameter snapshot
    - ``last_run`` (dict): result of ``run_case`` (has ``outputs``)
    - ``last_scan`` (dict): result of ``scan2d`` (has ``best``, ``fields``…)
    - ``images`` (dict[str,str]): ``{popcon, shape, profile}`` data-URI PNGs
    - ``timestamp`` (str): ISO-8601; defaults to now UTC
    - ``user`` (str): authenticated username
    - ``lang`` (str): ``"zh"`` (default) or ``"en"``
    """
    data = data or {}
    lang = (data.get("lang") or "zh").lower().startswith("zh") and "zh" or "en"
    is_zh = lang == "zh"

    def t(zh: str, en: str) -> str:
        return zh if is_zh else en

    config = data.get("config") or "—"
    config_label = data.get("config_label") or config
    preset = data.get("preset") or "—"
    user = data.get("user") or "anonymous"
    ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    version = _version()

    params = data.get("params") or {}
    last_run = data.get("last_run")
    last_scan = data.get("last_scan")
    images = data.get("images") or {}

    title = f"PolyFusion · {config_label} {t('模拟报告', 'Simulation Report')}"

    meta = (
        f"<div class='meta'>"
        f"<span><b>{t('位形', 'Config')}:</b> {_esc(config_label)}</span>"
        f"<span><b>{t('预设', 'Preset')}:</b> {_esc(preset)}</span>"
        f"<span><b>{t('用户', 'User')}:</b> {_esc(user)}</span>"
        f"<span><b>{t('时间', 'Time')}:</b> {_esc(ts)}</span>"
        f"<span><b>{t('版本', 'Version')}:</b> {_esc(version)}</span>"
        f"</div>"
    )

    summary = _summary_text(last_run, last_scan)
    output_rows = _outputs_rows(last_run)
    param_rows = _params_rows(params)
    scan_rows = (
        [
            ("xkey", last_scan.get("xkey"), ""),
            ("ykey", last_scan.get("ykey"), ""),
            ("nx", len(last_scan.get("x") or []), ""),
            ("ny", len(last_scan.get("y") or []), ""),
            ("n_invalid", last_scan.get("n_invalid", 0), ""),
        ]
        if last_scan
        else []
    )
    image_keys = [
        key
        for key in ("popcon", "shape", "profile")
        if _DATA_IMAGE_PNG_RE.match((images or {}).get(key) or "")
    ]

    sections = []
    sections.append(f"<h2 class='part-title'>{t('基础报告', 'Basic Report')}</h2>")
    sections.append(f"<h2>{t('一、结论摘要', '1. Summary')}</h2>")
    sections.append(f"<p>{_esc(summary)}</p>")
    sections.append(_errors_block(last_run))

    sections.append(f"<h2>{t('二、工作点输出', '2. Operating-point outputs')}</h2>")
    sections.append(_outputs_table(output_rows))

    sections.append(f"<h2>{t('三、输入参数', '3. Input parameters')}</h2>")
    sections.append(
        _kv_table(param_rows)
        if param_rows
        else '<div class="empty">无参数 / no parameters</div>'
    )

    sections.append(f"<h2>{t('四、POPCON 扫描摘要', '4. POPCON scan summary')}</h2>")
    sections.append(_scan_block(last_scan))

    sections.append(f"<h2>{t('五、图表', '5. Figures')}</h2>")
    sections.append(
        _image_block(
            images,
            "popcon",
            "图 1. POPCON 等值线与最佳区",
            "Fig 1. POPCON contours and operating window",
        )
    )
    sections.append(
        _image_block(
            images,
            "shape",
            "图 2. 几何 / 磁面",
            "Fig 2. Geometry / flux surface",
        )
    )
    sections.append(
        _image_block(
            images,
            "profile",
            "图 3. 剖面",
            "Fig 3. Profiles",
        )
    )

    disclaimer = (
        "非托卡马克位形为定性模型，绝对值待标定，请勿直接用于工程设计。"
        " 0-D 初筛：参数通过不一定能建成堆，但不通过几乎肯定不行。"
        if is_zh
        else "Non-tokamak configurations are qualitative models pending calibration; "
        "do not use absolute values for engineering design. 0-D screening: passing "
        "the filter does not guarantee a viable reactor, but failing it almost "
        "certainly rules one out."
    )
    sections.append(f"<h2>{t('六、注意事项', '6. Notes')}</h2>")
    sections.append(f"<div class='note'>{_esc(disclaimer)}</div>")

    sections.append(
        f"<h2 class='part-title'>{t('AI 分析报告', 'AI Analysis Report')}</h2>"
    )
    sections.append(
        f"<div id='aiReport' class='ai-report loading'>{t('加载中…', 'Loading…')}</div>"
    )

    body = "".join(sections)
    markdown_doc = _report_markdown(
        title=title,
        config=config,
        config_label=config_label,
        preset=preset,
        user=user,
        ts=ts,
        version=version,
        summary=summary,
        output_rows=output_rows,
        param_rows=param_rows,
        scan_rows=scan_rows,
        image_keys=image_keys,
        disclaimer=disclaimer,
        is_zh=is_zh,
    )
    safe_filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"polyfusion-{config}-{ts}.md")
    report_script = _report_script(markdown_doc, safe_filename)
    html_doc = (
        "<!DOCTYPE html>"
        f"<html lang='{lang}'><head><meta charset='utf-8'>"
        f"<title>{_esc(title)}</title>"
        f"<style>{_REPORT_CSS}</style></head><body>"
        f"<div class='wrap'><h1>{_esc(title)}</h1>"
        f"<div class='sub'>{_esc(config)} · preset {_esc(preset)}</div>"
        f"{meta}<div class='actions'><button id='saveReport'>"
        f"{t('保存报告', 'Save Report')}</button><button id='exportMarkdown'>"
        f"{t('导出 Markdown', 'Export Markdown')}</button>"
        f"<span id='saveReportStatus' class='status'></span></div>{body}"
        f"<div class='sub' style='margin-top:24px;text-align:right;color:#8995a8'>"
        f"PolyFusion · {_esc(version)} · {_esc(ts)}"
        f"</div></div>{report_script}</body></html>"
    )
    return html_doc
