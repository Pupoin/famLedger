# famLedger - 现代家庭财富与财务协作系统

<p align="center">
  <strong>隐私优先 · 账户流水与双向转账 · 全景桑基现金流 · 自动化规则清洗 · 多成员细粒度授权</strong>
</p>

---

## 📖 项目简介

**famLedger** 是一款为现代家庭与多成员团队量身定制的私有化部署财富管理与财务协作系统。系统采用 **本地优先 (Local-First)** 架构，在保障绝对数据主权与隐私安全的前提下，提供媲美现代商业金融产品的交互体验与专业严谨的财务核算能力。

无论是个人记账、夫妻共同开销核算、家庭多资产账户统一监控，还是亲友往来借贷与账单自动化清洗，famLedger 均能提供严密、直观、优雅的解决方案。

---

## ✨ 核心特性

### 1. 资产全景与账户流水与双向转账
- **多账户多币种管理**：支持储蓄卡、信用卡、投资证券、基金理财、公积金、现金及负债账户统一分类汇总。
- **真实账户净值与资产负债表**：动态计算总资产、总负债与实时净资产走势，杜绝资产浮夸。
- **纯粹财务口径**：内部转账、信用卡还款、借贷出资与回款严格与外部真实消费/收入解耦，彻底避免收支被重复虚增。
- **单笔交易明细拆分**：支持单笔流水多类目、多标签混合拆分记账。

### 2. 全景桑基图 (Cashflow Sankey)
- 遵循严谨的“**真实外部收入 → 资金流动池 (Cashflow Pool) → 消费与资产净流向**”可视化模型。
- 自动平抑跨期退款、实时抵扣负项，真实还原全月/全季度的现金流转全貌。

### 3. 自动化规则清洗引擎 (Rules Engine)
- **复合条件树**：支持 `AND` / `OR` / `NOT` 嵌套条件匹配，支持商户名、摘要、金额范围、账户、币种等组合筛选。
- **灵活管道动作**：自动补齐分类、自动挂载标签、标准化商户名称、标记排除统计或自动转账识别。
- **Dry-Run 预演仿真**：在历史流水样本上无痕模拟规则命中率与修改集，确认无误后支持一键历史全量回溯应用。

### 4. 亲友借贷与信贷台账 (Debts & Loans)
- **亲友往来 (IOU)**：清晰记录“谁欠我”与“我欠谁”，支持分期还款记录与结清归档。
- **商业贷款监控**：房贷、车贷、消费贷等负债本金、利率、月供周期性追踪与余额还款销账。

### 5. 多家庭与成员细粒度授权 (Granular RBAC)
- **家庭边界隔离**：多家庭组织间的数据与权限隔离，杜绝跨家庭数据串户。
- **账户级权限分配**：支持账户所有者将特定账户共享给指定家庭成员，并精细授予**“只读 (Read-Only)”**或**“读写 (Read-Write)”**及**“完全控制 (Full Control)”**权限，服务端接口全程强制校验防止越权 (IDOR)。

### 6. 企业级认证与自动化 API Key
- **双轨认证架构**：支持用户端会话 Cookie 与自动化 API Key 双轨并行。
- **安全 API Key 管理**：前缀安全脱敏展示、SHA-256 安全哈希存库、单次明文生成与一键撤销。
- **OIDC / SSO 单点登录集成**：原生兼容 Authelia、Keycloak、Authentik 等标准 OAuth2/OIDC 身份提供商，支持管理员动态配置与 JIT 自动建号。

---

## 🛠️ 技术栈

| 模块 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| **前端应用** | React 18, Vite 6, Tailwind CSS | 响应式现代化设计，支持桌面宽屏与移动端原生交互适配 |
| **图标与图表** | Lucide React, Recharts | 高清扁平化图表与动态交互 |
| **国际化与主题** | i18next, Tailwind Dark Mode | 中英双语支持，深色/浅色主题秒级无缝切换 |
| **后端服务** | Python 3.10+, FastAPI | 高性能异步 RESTful API 服务，依赖注入与严格参数校验 |
| **持久层与 ORM** | SQLModel, SQLAlchemy 2.0, SQLite / PostgreSQL 18 | 强类型数据模型，事务隔离、固定金额入账与日汇率缓存 |
| **认证与安全** | Bcrypt, HMAC-SHA256, URL-Safe Base64 | 强密码散列、会话签名防篡改与 API Key 哈希验证 |

---

## 🚀 快速启动

### 方式一：本地开发环境运行

在项目根目录安装依赖，并在 `backend/.env` 中配置 `SECRET_KEY`：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
```

同时启动前后端，网页使用 `http://localhost:8888`，API 由前端代理到后端的 8889 端口。前端开启 Vite 热更新，后端开启 Uvicorn 自动重载。开发模式不会自动备份数据库。

```bash
# 启动
.venv/bin/python scripts/dev.py start

# 重启 / 停止
.venv/bin/python scripts/dev.py restart
.venv/bin/python scripts/dev.py stop

# 生产环境编译构建
npm --prefix frontend run build
```

运行日志和进程记录位于 `.cache/development/`。

---

## 🐳 Docker 部署

```bash
cp .env.docker.example .env.docker
# 填写 SECRET_KEY 与 POSTGRES_PASSWORD，再启动
docker compose --env-file .env.docker up -d --build
```

默认使用 PostgreSQL 18，页面端口为 8000。单独运行应用镜像也支持 SQLite：设置 `DATABASE_URL=sqlite:////app/data/famledger.db` 并持久化 `/app/data`，不依赖 PostgreSQL 服务。直接使用 HTTP 时需设置 `COOKIE_SECURE=false`；HTTPS 部署使用 `true`。

## 📁 开发与接口文档

- [文档索引](./docs/README.md)
- [现金流与桑基图计算口径](./docs/CASHFLOW_SANKEY_SPEC.md)
- [POST 接口与外部流水 ID](./postapi.md)
- [账单服务](./services/bill/README.md)

## ✅ 测试

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

PostgreSQL 集成测试使用独立的 `fix104_verify` 测试库，配置 `FAMLEDGER_TEST_PG_URL` 后运行 `backend/tests/test_fix104_postgres.py`；未配置时明确跳过。

---

## 🔒 隐私与安全声明

famLedger 坚持以隐私安全为第一要务：
1. **零外部数据上报**：没有第三方跟踪脚本，不收集任何用户使用行为与账目数据。
2. **本地文件存储**：账户流水与配置存储于自托管的 SQLite 或 PostgreSQL 数据库中。密码与 API Key 保存哈希，原始 API Key 仅在生成时展示。
3. **备份防灾**：内置本地自动旋转备份机制，确保在意外断电或数据损坏时随时可快速还原。
