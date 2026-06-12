# PolyFusion · 多位形零维聚变系统设计平台

Multi-configuration 0-D fusion system design platform with web GUI.

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
2. **New + Web Service** → 选择 `marxtein/PolyFusion` 仓库
3. 配置：
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app/server.py`
4. 点 **Create Web Service**
5. 部署完成后获得公网网址（如 `https://polyfusion.onrender.com`）

> `app/server.py` 已适配 Render 环境（自动读取 `$PORT` 环境变量，监听 `0.0.0.0`）。

---

## 项目结构

```
PolyFusion/
├── polyfusion/              # 计算核心
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

---

## License

MIT
