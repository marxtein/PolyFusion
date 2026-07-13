# VSC (veloalpha system code) · 多位形零维聚变系统设计平台

[![Live Demo](https://img.shields.io/badge/Live%20Demo-polyfusion%2Ddang.onrender.com-brightgreen?style=flat-square)](https://polyfusion-dang.onrender.com/)
[![GitHub](https://img.shields.io/github/stars/marxtein/PolyFusion?style=flat-square)](https://github.com/marxtein/PolyFusion)

VSC (veloalpha system code) is a multi-configuration 0-D fusion system design platform with a web GUI.

支持托卡马克、磁镜、场反位形（FRC）、偶极场、仿星器等多种位形的零维参数扫描与设计。

---

## 支持的位形

| 位形 | 状态 |
|---|---|
| 托卡马克（Tokamak） | ✅ 已验证（golden test） |
| 磁镜（Magnetic Mirror） | 🔶 初步集成 |
| 场反位形（FRC） | 🔶 初步集成 |
| 偶极场（Dipole） | 🔷 框架就绪 |
| 仿星器（Stellarator） | 🔷 框架就绪 |

---

## 快速开始

### 依赖

- Python ≥ 3.10
- numpy ≥ 1.26.0

### 安装

```bash
git clone https://github.com/marxtein/PolyFusion.git
cd PolyFusion
pip install -r requirements.txt
```

### 运行（本地）

```bash
# CLI 单点计算
python -m polyfusion

# Web GUI（推荐）
python app/server.py
# 然后打开浏览器访问 http://127.0.0.1:8765
```

---

## 部署到 Render（免费公网访问）

1. 打开 [render.com](https://render.com)，用 GitHub 登录
2. **New + Web Service** → 选择承载 VSC 的仓库（当前为 `marxtein/PolyFusion`）
3. 配置：
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app/server.py`
4. 点 **Create Web Service**
5. 部署完成后获得 Render 分配的公网网址

> `app/server.py` 已适配 Render 环境（自动读取 `$PORT` 环境变量，监听 `0.0.0.0`）。

---

## 项目结构

```
VSC/
├── polyfusion/              # 计算核心 Python 包
│   ├── tokamak.py          # 托卡马克 0-D 求解器
│   ├── io.py               # 输入输出接口
│   ├── scan.py             # 二维参数扫描
│   └── configs/           # 各位置形模型
│       ├── base.py
│       ├── tokamak.py
│       ├── mirror.py
│       ├── frc.py
│       ├── dipole.py
│       └── stellarator.py
├── app/                    # Web GUI
│   ├── server.py           # 本地 HTTP 服务器（stdlib，无 Flask 依赖）
│   └── index.html         # 前端页面（Plotly.js 渲染）
├── docs/                   # 设计文档
└── requirements.txt
```

---

## 使用说明

1. 启动 `app/server.py` 后，在浏览器中打开 `http://127.0.0.1:8765`
2. 选择位形（默认托卡马克）
3. 调整参数，点击计算
4. 结果以交互式图表展示，可导出

### 规则分析报告

报告分析由 `polyfusion/deterministic_report.py` 在本地按运行点、POPCON
扫描、默认工作窗准则和位形专属指标生成，不需要在线模型或 API key。
生成规则通过五个位形各 64 个参数组合（共 320 个 payload 和 320 份
`gpt-5.4` 对照报告）完成全量回放验证；可复现语料、对照报告、规律分析和
验证结果位于 `artifacts/deterministic-report-corpus/`。公网界面的分析开关
目前仍保持关闭，服务端报告接口不再为每次请求调用在线 AI。

---

## 非环形位形的回旋辐射模式

磁镜、FRC 和偶极场均提供两种互斥的 `Pcycl` 计算口径：

- 默认 `use_tauC=0`：采用各位形自己的快速工程公式。磁镜和 FRC 使用
  \(B^{2.5}\) 体积矩与全局光学半径；偶极场采用有限环赤道磁通壳代理。
- `use_tauC=1`：用户输入等效损失时间 `tauC`，按电子热储能计算 `Pcycl = Eth_e/tauC`。

输出 `tauC_eff` 表示当前口径对应的等效回旋辐射损失时间。内置公式是从
Trubnikov/Kukushkin 标度外推的 0D 工程近似，不是完整辐射输运或射线追踪模型。
公式背景见 [IAEA FEC 2008 TH/P3-10](https://www-pub.iaea.org/MTCD/Meetings/FEC2008/th_p3-10.pdf)。

托卡马克和仿星器另提供 `cyclotron_B_nonuniform` 开关：

- 关闭（默认）：沿用均匀参考磁场的原公式。
- 开启：托卡马克采用 \(B_T(R)=B_0R_0/R\) 的 Miller 体积矩；仿星器采用
  一阶近轴 \(B/B_0=1+\bar\eta r\cos\theta\) 的体积矩。

输出 `cyclotron_B25_factor` 是乘到原 `Pcycl` 上的无量纲修正。该开关只评估
磁场幅值不均匀性的快速影响，不包含 CYNEQ 类频率、吸收、反射和非局域输运。

---

## License

MIT
