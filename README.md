# famLedger

**Self-hosted household finance · 自托管家庭财务管理**

[English](#english) | [简体中文](#chinese)

<a id="english"></a>

## English

famLedger manages personal and household finances through account activity, multi-currency transactions, shared accounts, and scheduled payments. The React interface supports English and Simplified Chinese on desktop and mobile.

### Features

- **Accounts and balances:** bank accounts, cash, investments, credit cards, and loans. Balances are calculated from recorded account activity, including opening balances and reconciliation adjustments. Asset and liability totals sum all accounts you own or can access through sharing, including archived accounts and accounts excluded from spending reports; primary and supplementary cards count their own activity once. Standalone personal debt notes remain in debt management and are not added to account balance totals.
- **Multi-currency booking:** preserve original transaction amounts and currencies, record fixed account settlements, and convert reports into the user's display currency using historical exchange rates cached in the database. Transactions awaiting an exchange rate remain pending until they can be booked.
- **Transfers and refunds:** paired internal transfers, credit-card repayments, full and partial refunds, refunds allocated across multiple expenses, transaction splits, and tags.
- **Reports and budgets:** net worth, income and spending reports, cashflow Sankey diagrams, spending calendars, merchant charts, and category budgets. The privacy toggle hides monetary values in charts.
- **Payment plans:** editable scheduled transfers and loan repayments, automatic or confirmed execution, rate changes, repayment phases, dated interest-free and interest-only periods, and prepayments.
- **Household collaboration:** invitations, account ownership, read-only, read-write, and full-control sharing. Primary and supplementary credit cards can belong to different household members, with sharing required for the primary card owner to view the supplementary card.
- **Rules and automation:** nested conditions, categorization, merchant normalization, tags, previews, and full JSON import/export. Lower priority numbers run first; the first category match wins. Unmatched transactions use Other, and manual categories are preserved. Optional Microsoft Graph email-bill ingestion runs as a separate service.
- **Authentication and preferences:** local login, configurable OIDC sign-in, revocable API keys stored as hashes, language and display-currency preferences, and light, dark, or automatic themes.

When an OIDC identity first matches an existing account's email or username, famLedger asks for that account's password once before linking. Later sign-ins use the stored external identity. You can also link or unlink a provider under **Settings → Profile → Single sign-on links**, including when the two accounts use different email addresses. Unlinking requires the local password when one exists and must leave another usable login method; it preserves ledger data and signs out other devices.

### Technology

| Layer | Technology |
| --- | --- |
| Interface | React 18, Vite 6, Tailwind CSS, i18next |
| Charts and icons | Recharts, Lucide React |
| API | Python, FastAPI, Pydantic |
| Database | SQLModel, SQLAlchemy, SQLite or PostgreSQL; Docker Compose uses PostgreSQL 18 |
| Authentication | bcrypt password hashing, signed sessions, hashed API keys, OIDC |
| Tests | pytest, Vitest |

### Local development

Requirements: Python 3.10+, Node.js 22.12+, and npm. Run these commands from the repository root:

```bash
git clone git@github.com:Pupoin/famLedger.git
cd famLedger

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci

cp backend/config.example.py backend/config.py
cp backend/.env.example backend/.env
```

Generate a secret, then replace the `SECRET_KEY` placeholder in `backend/.env` with the generated value:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Start, restart, or stop both development servers:

```bash
.venv/bin/python scripts/dev.py start
.venv/bin/python scripts/dev.py restart
.venv/bin/python scripts/dev.py stop
```

- Website: <http://localhost:8888>
- Backend: <http://localhost:8889>; the frontend proxies API requests to this port.
- API documentation: <http://localhost:8889/docs>
- Vite hot updates and backend automatic reload are enabled. Logs and process records are stored in `.cache/development/`.
- SQLite is used by default, with the database at `backend/famledger.db`. Tables are initialized at startup. The first registered user becomes the system administrator; default categories and editable rules are initialized when a household is created.
- Development mode does not create automatic database backups.

Build the frontend with `npm --prefix frontend run build`.

### Docker deployment

Docker Compose uses PostgreSQL 18 and serves the compiled frontend and API from the same application container.

```bash
cp .env.docker.example .env.docker
# Set independent random values for SECRET_KEY and POSTGRES_PASSWORD.
# For direct HTTP access, set COOKIE_SECURE=false; use true with HTTPS.
docker compose --env-file .env.docker up -d --build famledger
```

Open <http://localhost:8000>. Change `FAMLEDGER_PORT` in `.env.docker` to use another port. The command starts the application and its database dependency. The optional [Mailbridge](./services/mailbridge/README.md) has its own Docker Compose, Microsoft authentication page and mail scheduler. It posts original-currency transactions to famLedger using the configured user API Key.

SQLite can also run in a standalone application container:

```bash
docker build -t famledger:local .
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker run -d --name famledger-sqlite \
  -p 8000:8000 \
  -e SECRET_KEY \
  -e ENV=production \
  -e COOKIE_SECURE=false \
  -e DATABASE_URL=sqlite:////app/data/famledger.db \
  -v famledger-sqlite-data:/app/data \
  famledger:local
```

Persist the database and `/app/data` across container replacements. Production mode creates rotating backups; PostgreSQL deployments also need their database volume preserved.

Docker Compose uses local bind mounts: `./postgres-data/` for PostgreSQL and `./famledger-data/` for application files. Both directories are excluded from Git and Docker build contexts. Keep them when recreating containers.

### Tests

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build

# Run Mailbridge tests separately to avoid a collision between backend module names.
.venv/bin/python -m pip install httpx -r services/mailbridge/requirements.txt
(cd services/mailbridge && ../../.venv/bin/python -m pytest tests -q)
```

PostgreSQL tests are optional in a local run and are skipped unless their isolated test databases are configured:

- Main application: set `FAMLEDGER_TEST_PG_URL` to a database named `fix104_verify`, then run `backend/tests/test_fix104_postgres.py`. The real dump/restore test additionally requires the dedicated `famledger-fix104-pg-verification` container and `FAMLEDGER_TEST_PG_CONTAINER` / `FAMLEDGER_TEST_PG_MOUNT`; setup details are in that test file.

### Data and configuration

Ledger data resides in the configured SQLite or PostgreSQL database. Exchange-rate retrieval contacts an external provider; OIDC and email ingestion contact their configured services. Passwords and API keys are stored as hashes, and newly generated API keys are shown in plaintext only once. Keep environment secrets, databases, token caches, uploads, audit logs, and backups out of Git.

### Documentation

The following implementation guides are currently written in Chinese:

- [Documentation index](./docs/README.md)
- [Cashflow and Sankey calculation rules](./docs/CASHFLOW_SANKEY_SPEC.md)
- [POST APIs and external transaction IDs](./postapi.md)
- [Mailbridge email ingestion](./services/mailbridge/README.md)

---

<a id="chinese"></a>

## 简体中文

famLedger 通过账户活动、多币种流水、共享账户和定期支付计划管理个人与家庭财务。React 界面支持英语和简体中文，适配电脑与手机。

### 功能

- **账户与余额**：管理银行账户、现金、投资、信用卡和贷款。余额由已记录的账户活动计算，包含期初余额和对账调整。资产与负债合计包含本人及显式共享的全部账户，包括停用及不计入收支报表的账户；主副卡按本卡活动各累计一次。独立的个人借贷记录保留在借贷管理中，不额外叠加到账户余额合计。
- **多币种入账**：保留交易原始金额和币种，固定账户结算金额；报表通过数据库缓存的历史汇率换算为用户设置的展示币种。缺少汇率的交易先进入待换汇队列，取得汇率后再入账。
- **转账与退款**：支持成对的内部转账、信用卡还款、全额或部分退款、多笔消费的退款分配、交易拆分和标签。
- **报表与预算**：包含净资产、收支报表、现金流桑基图、消费日历、商户图表和分类预算。隐私开关会隐藏图表中的金额。
- **支付计划**：可编辑定期转账和贷款还款计划，支持自动执行或确认后执行、分阶段利率与还款方式、按时间段设置免息和仅还利息，以及提前还款。
- **家庭协作**：支持邀请、账户所有权，以及只读、读写、完全控制三档共享权限。信用卡主副卡可分属不同家庭成员；副卡需共享给主卡所有者，保证其能够查看副卡流水。
- **规则与自动化**：支持嵌套条件、分类、商户名称规范化、标签、预演及完整 JSON 导入导出。优先级数字越小越先执行，分类按首条命中生效，未命中归入「其他」，保留手动分类。可选的 Microsoft Graph 邮件账单抓取由独立服务运行。
- **认证与偏好**：支持本地登录、可配置的 OIDC 登录、哈希存储且可撤销的 API Key、语言与展示币种设置，以及浅色、深色、自动主题。

首次 OIDC 登录如果与已有账户的邮箱或用户名相同，famLedger 会要求输入一次该本地账户的密码，确认后才关联；之后按已绑定的外部身份登录。也可在 **设置 → 个人资料与身份设置 → 单点登录关联** 中主动关联或取消关联，支持双方邮箱不同的情况。取消关联时，有本地密码的账户需输入密码确认，并且必须保留另一种可用的登录方式；账本数据会保留，其他设备需重新登录。

### 技术栈

| 模块 | 技术 |
| --- | --- |
| 界面 | React 18、Vite 6、Tailwind CSS、i18next |
| 图表与图标 | Recharts、Lucide React |
| API | Python、FastAPI、Pydantic |
| 数据库 | SQLModel、SQLAlchemy、SQLite 或 PostgreSQL；Docker Compose 使用 PostgreSQL 18 |
| 认证 | bcrypt 密码哈希、签名会话、API Key 哈希、OIDC |
| 测试 | pytest、Vitest |

### 本地开发

需要 Python 3.10+、Node.js 22.12+ 和 npm。在项目根目录运行：

```bash
git clone git@github.com:Pupoin/famLedger.git
cd famLedger

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci

cp backend/config.example.py backend/config.py
cp backend/.env.example backend/.env
```

生成随机密钥，将输出填入 `backend/.env`，替换 `SECRET_KEY` 的占位值：

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

同时启动、重启或停止前后端：

```bash
.venv/bin/python scripts/dev.py start
.venv/bin/python scripts/dev.py restart
.venv/bin/python scripts/dev.py stop
```

- 页面：<http://localhost:8888>
- 后端：<http://localhost:8889>；前端将 API 请求代理至该端口。
- API 文档：<http://localhost:8889/docs>
- 前端开启 Vite 热更新，后端开启自动重载。日志和进程记录位于 `.cache/development/`。
- 默认使用 SQLite，数据库位于 `backend/famledger.db`，启动时初始化数据表。第一个注册用户成为系统管理员；创建家庭时初始化默认分类及可编辑的分类规则。
- 开发模式不自动备份数据库。

前端构建命令为 `npm --prefix frontend run build`。

### Docker 部署

Docker Compose 使用 PostgreSQL 18，编译后的前端页面和 API 由同一个应用容器提供。

```bash
cp .env.docker.example .env.docker
# 为 SECRET_KEY 和 POSTGRES_PASSWORD 分别设置独立的随机值。
# 直接通过 HTTP 访问时设置 COOKIE_SECURE=false；HTTPS 下使用 true。
docker compose --env-file .env.docker up -d --build famledger
```

访问 <http://localhost:8000>。可以在 `.env.docker` 中修改 `FAMLEDGER_PORT`。上述命令启动应用及其数据库依赖。[Mailbridge 邮件抓取](./services/mailbridge/README.md)有自己的 Docker Compose、微软认证页面和邮件调度器，通过所配置用户的 API Key 向 famLedger POST 原币交易。

也可以使用独立应用容器运行 SQLite：

```bash
docker build -t famledger:local .
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker run -d --name famledger-sqlite \
  -p 8000:8000 \
  -e SECRET_KEY \
  -e ENV=production \
  -e COOKIE_SECURE=false \
  -e DATABASE_URL=sqlite:////app/data/famledger.db \
  -v famledger-sqlite-data:/app/data \
  famledger:local
```

更换容器时需保留数据库和 `/app/data`。生产模式会生成轮转备份；使用 PostgreSQL 时还需持久化数据库服务的数据卷。

Docker Compose 使用本地目录挂载：`./postgres-data/` 保存 PostgreSQL 数据，`./famledger-data/` 保存应用文件。两个目录均已排除出 Git 和 Docker 构建上下文，重新创建容器时应保留。

### 测试

```bash
.venv/bin/python -m pytest backend/tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build

# 独立运行账单测试，避免两个 backend 模块名称冲突。
.venv/bin/python -m pip install httpx -r services/mailbridge/requirements.txt
(cd services/mailbridge && ../../.venv/bin/python -m pytest tests -q)
```

本地运行时，PostgreSQL 测试需要额外配置独立测试库，否则会明确跳过：

- 主应用：设置 `FAMLEDGER_TEST_PG_URL`，数据库名必须为 `fix104_verify`，再运行 `backend/tests/test_fix104_postgres.py`。真实备份恢复测试还需专用容器 `famledger-fix104-pg-verification`，以及 `FAMLEDGER_TEST_PG_CONTAINER`、`FAMLEDGER_TEST_PG_MOUNT`；具体设置见测试文件。

### 数据与配置

账本数据保存在配置的 SQLite 或 PostgreSQL 数据库中。获取汇率时会访问外部汇率服务；OIDC 和邮件抓取会访问对应的已配置服务。密码和 API Key 保存哈希，新生成的 API Key 仅展示一次明文。环境密钥、数据库、令牌缓存、上传文件、审计日志和备份不应提交到 Git。

### 文档

- [文档索引](./docs/README.md)
- [现金流与桑基图计算口径](./docs/CASHFLOW_SANKEY_SPEC.md)
- [POST 接口与外部流水 ID](./postapi.md)
- [Mailbridge 邮件抓取](./services/mailbridge/README.md)
