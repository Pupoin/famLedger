# 招行账单自动化（Python + FastAPI + ECharts）

本项目用于：自动化读取招行邮件账单 → 智能解析 → 写入 PostgreSQL → 通过 FastAPI + ECharts 提供高性能交互式仪表盘。

---

## 1. 目录结构（前后端分离架构）

### 📂 `backend/` - 数据核心与调度
负责数据的“心脏”跳动：
- `auth/`：基于 MSAL 的 Microsoft Graph 认证模块。
- `ingest/`：账单抓取、正则解析、入库、数据统计。
- `notify/`：Windows 系统通知推送。
- `run.py`：**核心调度器**，负责定时启动抓取任务。

### 📂 `front/` - 展示层
负责数据的“颜值”与交互：
- `main.py`：FastAPI 接口服务，提供数据 API 及静态页面托管。
- `logic.py`：前端专用业务逻辑（如 Sankey 数据构建、分类匹配）。
- `static/`：
    - `index.html`：响应式单页应用，支持手机端/PC端、深色模式。
    - `charts.js`：基于 ECharts 的深度交互逻辑（Sankey 点击、缩放等）。

### 📂 `data/` - 共享数据目录
- `category_rules.json`：分类匹配规则（可通过网页端 GUI 直接修改）。
- `auth_state.json`：前后端共享的认证状态文件。

---

## 2. 运行与配置

此目录提供独立的邮件账单调度器，以及可选的账单看板。主项目的 `docker-compose.yml` 通过 `famledger-bill` 启动调度器；主应用的页面由 famLedger 提供，不会启动旧的 Sure Compose。

```bash
# 在 services/bill 中安装依赖并配置独立账单库、Graph 应用和令牌缓存
python -m pip install -r backend/requirements.txt
cp .env.example .env
python -m backend.run
```

`POSTGRES_DSN` 指向账单服务自身的 PostgreSQL 数据库。调度器使用设备码授权的 Microsoft Graph 会话读取邮件，不直接写 famLedger 的数据库。

### 推送到 famLedger

配置 `FAMLEDGER_API_URL`、`FAMLEDGER_API_TOKEN`；系统服务令牌须在主应用中绑定到活动家庭。推送通过 `/api/v1/transactions`，以账户和 `external_id` 去重；待换汇响应会保留同步状态等待后续入账。

看板属于独立可选服务，入口为 `front/main.py` 与 `front/Dockerfile`。其数据库与认证配置见下文；主项目 Compose 不发布这个看板。

### 推送到 Sure

`bill/.env.sure` 保存 Sure API 地址、专用读写 API Key 和开关（请勿提交密钥）。
`SAVE_EMAILS=true` 时，后端把所配置邮件文件夹内抓到的所有 Graph 邮件先存到 `bill_emails`，
用邮件 ID 与内容指纹防重复，并从该表读取未处理邮件进行解析。首次使用 `LOOKBACK_DAYS_*`
做历史回看，此后每次只从上次成功抓取时间继续（重叠一天以防漏收）。
每封邮件保存 Graph ID、发件人、主题、接收时间、完整正文和正文预览；不下载附件或原始 MIME。
`SAVE_EMAILS=false` 时，新邮件仍直接解析并写入 `CMB_bill`，Sure 仍从账单表同步；
邮件正文随交易保存供 Sure notes 使用，但新邮件不写入 `bill_emails`。
切换开关前已缓存且未处理的邮件仍会先处理。
`SURE_SYNC_ENABLED=true` 时，
解析出的交易写入 `CMB_bill`，再从已提交的账单记录中读取待同步交易并推送 Sure。
成功创建或 Sure 判定重复后记录同步时间；失败的记录留待下一轮。
`SURE_SYNC_DRY_RUN=true` 只检查匹配情况、不写入 Sure；
改为 `false` 才会创建交易或缺失的分类。账户按“金融机构名称＋账户名称”精确匹配；
匹配不到或不唯一的流水会写入后端告警日志。邮件表以 Graph 邮件 ID 和内容指纹双重去重，
账单表按账户、规范化商户、精确时间、原币金额和币种去重。

---

## 3. 环境变量配置 (`.env`)

```env
# Microsoft Graph 认证
GRAPH_CLIENT_ID=你的 Azure App Client ID
GRAPH_TENANT_ID=common
GRAPH_USER_ID=me

# 数据库配置
POSTGRES_PASSWORD=your_password
POSTGRES_DSN=postgresql://postgres:your_password@bill-postgres:5432/personal_cost

# 抓取逻辑
CREDIT_FOLDER=credits
DEBIT_FOLDER=Debit_card
LOOKBACK_DAYS_CREDIT=20
LOOKBACK_DAYS_DEBIT=20
BILL_SYNC_INTERVAL_SECONDS=600
SAVE_EMAILS=true

# 日志
LOG_LEVEL=INFO
LOG_FILE_PATH=logs/backend.log
```

---

## 4. 核心功能特性

### 🔐 认证管理 (Sidebar 集成)
- **无感刷新**：前端实时感知后端认证状态。
- **设备码登录**：认证失效时，侧边栏直接显示 8 位验证码并提供一键授权链接。

### 📊 交互式图表
- **Sankey 资金流向**：点击节点可弹出详细账单流水，支持多维度排序。
- **日历热力图**：560px 超大高度，完美展示每日消费强度。
- **消费趋势**：支持自动/线性/Log 轴切换，适配大额消费波动。

### 📱 移动端深度优化
- **动态视口 (100dvh)**：修复手机浏览器地址栏遮挡问题。
- **智能浮标 (FAB)**：支持自由拖拽、自动贴边、闲时自动半透明隐藏。
- **手势操作**：支持左右滑动快速切换月份/年份，并带有透明提示框。

### 🏷️ 分类管理 GUI
- 无需修改代码，直接在侧边栏“分类管理”中：
    - 新增/删除正则表达式匹配规则。
    - 自定义分类 Emoji。
    - 更改后“保存生效”将触发全量数据重新分类。

---

## 5. 测试与校验

在宿主机运行（需安装 pytest 和 backend/requirements.txt 中的依赖）：

```bash
python -m pytest tests -q
```

---
