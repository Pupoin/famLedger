# Mailbridge / 微软邮件账单桥接

Mailbridge connects a Microsoft mailbox, parses bank statement emails and POSTs original-currency transactions to famLedger. It has a small Microsoft authentication page and a mail scheduler. It contains no charts, separate financial ledger, PostgreSQL, Sure integration or exchange-rate calculation.

Mailbridge 连接 Microsoft 邮箱，解析银行账单邮件，并通过 POST 写入 famLedger。页面只用于微软认证。金额换算、余额、分类、退款撮合和图表由 famLedger 负责。

## Docker

This directory can be deployed on its own. / 本目录可以单独复制和部署。

```bash
cp .env.example .env
# Fill in GRAPH_CLIENT_ID, FAMLEDGER_API_URL and FAMLEDGER_API_TOKEN.
# 配置自己的微软应用、famLedger 后端地址和目标用户 API Key。
docker compose up -d --build
docker compose ps
```

Open <http://localhost:8502>, click **Sign in with Microsoft / 登录 Microsoft**, and complete the device-code login. Existing Microsoft token caches are reused. The page only binds to the local computer.

访问 <http://localhost:8502> 完成设备码授权。已有微软登录缓存会复用。界面只有认证状态、设备码和登录按钮；不再提供账单看板、交易修改和统计接口。

For domain/IP access through a reverse proxy, add its hostname to `MAILBRIDGE_ALLOWED_HOSTS` in `.env`, for example `localhost,127.0.0.1,mailbridge.example.com`. Use comma-separated hostnames or IPv4 addresses without a scheme, port or path. Localhost access and container health checks remain allowed. After editing `.env`, recreate `auth-web`; code updates also require rebuilding its image.

通过域名/IP 或反向代理访问时，在 `.env` 的 `MAILBRIDGE_ALLOWED_HOSTS` 中加入实际访问主机，例如 `localhost,127.0.0.1,mailbridge.example.com`。多个主机用英文逗号分隔，不包含协议、端口或路径；支持 `*.example.com` 子域名通配，本机地址始终保留。修改配置后重建认证网页容器：`docker compose up -d --build --force-recreate --no-deps auth-web`。

The page checks the existing MSAL cache first. A valid login displays **No need to sign in again**, with **Force reauthentication** available. A device code is displayed only while its current login flow is active; the page uses Microsoft's returned sign-in URL and shows the remaining validity. Restarting the container does not redisplay an orphaned code.

页面先检查现有 MSAL 登录缓存；有效时显示“无需重新认证”，并提供“强制重新认证”按钮。设备码只在本次认证流程运行期间显示，授权地址使用微软实际返回的地址，并显示剩余有效期。容器重启后不继续展示失去认证流程的旧码。

Microsoft's own sign-in page uses the display name of the Azure application identified by `GRAPH_CLIENT_ID`. If it still says **bill**, open Microsoft Entra **App registrations**, select that application, and change its name to **mailbridge** under **Branding & properties**. Keep the existing client ID. Then request a new code using **Force reauthentication**; a local page title or Docker service rename cannot change Microsoft's application name. [Microsoft app registration documentation](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app).

微软窗口若显示“你现在已登录到 bill”，需要在 Microsoft Entra **应用注册 → 对应 `GRAPH_CLIENT_ID` 的应用 → 品牌和属性（Branding & properties）**中，将应用名称改为 **mailbridge** 并保存。保持客户端 ID 不变，然后在本地认证页点击“强制重新认证”，使用新设备码验证。这个名称由微软端应用注册控制，本地网页或 Docker 服务改名不会修改它。

## Configuration / 配置

All configuration is in `.env`. Do not publish this file or token caches.

所有设置统一放在 `.env`；不再使用 `.env.docker`。

| Setting | Meaning / 含义 |
| --- | --- |
| `TZ` | Container/log timezone; defaults to `Asia/Shanghai` (UTC+8) / 容器及日志时区，交易时间仍按 UTC 存储 |
| `MAILBRIDGE_ALLOWED_HOSTS` | Auth-page host allowlist, comma-separated; defaults to local hosts / 认证网页允许访问的域名或 IPv4 地址，以英文逗号分隔 |
| `GRAPH_CLIENT_ID` | Your Azure app with public client/device-code flow enabled / 开启公共客户端设备码流程的微软应用 |
| `GRAPH_TENANT_ID` | Usually `common` / 一般为 `common` |
| `GRAPH_USER_ID` | Usually `me` / 一般为 `me` |
| `FAMLEDGER_API_URL` | famLedger backend origin / famLedger 后端地址 |
| `FAMLEDGER_API_TOKEN` | Target user's personal API Key / 目标用户的个人 API Key，例如 jj；交易归属由该 Key 决定 |
| `MAILBRIDGE_PULL_ENABLED` | `true` to fetch Microsoft mail into SQLite; `false` pauses fetching / 独立控制邮件拉取，默认 `true`，不需要 famLedger Key |
| `MAILBRIDGE_POST_ENABLED` | `true` to parse and POST cached mail; `false` pauses delivery / 独立控制本地缓存推送，默认 `false`；暂停时保留全部推送状态 |
| `CREDIT_FOLDER`, `DEBIT_FOLDER` | Bank email folders / 信用卡、借记卡邮件文件夹 |
| `LOOKBACK_DAYS_CREDIT`, `LOOKBACK_DAYS_DEBIT` | Historical lookback; changing the value re-scans that folder once / 历史回看天数；修改数值后重扫一次，随后恢复增量同步 |
| `MAILBRIDGE_REPLAY` | Empty normally; `10d@run-1` replays the past 10 days, `all@run-1` replays all cached history / 平时留空；天数与操作标记合并为一个参数，同值重启续传 |
| `MAILBRIDGE_DATABASE_PATH` | Independent SQLite mail cache; default `data/mailbridge.db` / 独立邮件缓存数据库 |
| `MAILBRIDGE_SYNC_INTERVAL_SECONDS` | Default 600 seconds / 默认 600 秒 |
| `MAILBRIDGE_TASK_TIMEOUT_SECONDS` | Default 1000 seconds / 默认任务超时 1000 秒 |

When famLedger runs on this computer outside Docker, use its published port (current local Docker: `http://host.docker.internal:8888`). For another deployment use its reachable backend URL. Generate the personal API Key in that user's famLedger settings. Never use a different user's Key by accident.

主应用运行在宿主机时，当前容器中配置 `http://host.docker.internal:8888`；其他部署填写其可访问后端地址。在目标用户的 famLedger 设置中创建 API Key。当前 famLedger 已迁入空库 Docker，地址为 `http://localhost:8888`。Mailbridge 的旧 Key 已清空、自动同步已暂停；注册新账号后填写该账号的新 Key，再启用。

## Delivery / 推送

- POST endpoint: `/api/v1/transactions`, authenticated with `X-Api-Key`.
- Original amount and currency are preserved. famLedger books any required exchange rate.
- Accounts are sent as `招商银行信用卡:1234` or `招商银行借记卡:1234`. Set **External identifier** in famLedger's account editor to that complete value, keeping leading zeros. Full identifiers are matched exactly before suffix-only identifiers or account names, so changing the display name does not change routing. A suffix-only identifier additionally requires the bank and card type to match. Only accounts with an empty identifier fall back to name matching. Ambiguous matches return HTTP 409 and remain queued until corrected. Unmatched cards are created with the complete POST account identifier saved as `external_identifier`; the institution contains only the bank name (`招商银行`), with the card type stored separately.
- Stable `external_id` uses account tail, normalized merchant, exact UTC+8 timestamp, signed original amount and currency; duplicates are acknowledged without overwriting transactions.
- An independent SQLite database, `data/mailbridge.db`, stores full `body.content` and content type, subject, sender/from, to/cc/bcc recipients, sent/received timestamps and the original Graph message JSON. It stores delivery attempts/status separately for each target.
- Microsoft account partitions and immutable message IDs prevent mixing mailboxes and repeated body downloads. [Graph delta synchronization](https://learn.microsoft.com/en-us/graph/delta-query-messages) fetches changes after the initial lookback. A checkpoint advances only after mail is cached durably.
- Parsing and POST read the local cache. Failed deliveries remain queued; changing the target URL or API Key replays cached mail to the new target. Original cached mail is retained even if it is deleted from Microsoft.
- `pending_fx` means famLedger has stored the transaction for later currency booking; it is acknowledged and not silently discarded.

POST 使用 `X-Api-Key`，原币金额和币种原样发送。`external_id` 稳定生成，famLedger 负责去重，不覆盖已有交易。完整邮件先保存到独立 SQLite，再从本地解析并推送。保留标题、完整正文及类型、发件人、代发人、收件人/抄送/密送、收发时间和原始 JSON。历史查询和失败重试无需重复请求微软；新邮件使用增量同步。缓存成功后才推进微软抓取进度，推送失败单独保留重试状态。待换汇交易由 famLedger 保存。原 PostgreSQL 账本已移除。

账户以 `招商银行信用卡:1234` 或 `招商银行借记卡:1234` 发送。在 famLedger 的“编辑账户信息”中，把“外部账户标识”设为这一完整字符串，保留前导零。完整标识优先精确匹配，修改显示名称不影响导入。仅填写四位尾号的标识还须匹配银行和卡类型；未填写标识的账户才按名称回退匹配。多个候选返回 HTTP 409，邮件继续留在待推队列，修正后重试。未匹配的银行卡会自动新建，并把 POST 的完整账户标识保存到 `external_identifier`；账户名称为 `招商银行 1234`，金融机构只保存 `招商银行`，卡类型独立保存。

New account names contain the bank and suffix only (for example, `招商银行 1234`), with the credit/debit type stored in its own field. The complete external identifier still distinguishes card types.

Runtime files / 运行文件：`data/msal_token_cache.json`、`data/auth_state.json`、`data/mailbridge.db`。均不进入 Git 或镜像。日志只输出到容器控制台，不创建 `logs/` 目录；使用 `docker compose logs` 查看。 / Logs go to the container console only.

Delivery failures log the exception type, HTTP status when available, and an actionable reason. Expected queued failures produce one summary without duplicate tracebacks; unexpected failures retain one traceback. Credentials, request headers and complete response/mail bodies are not included in POST error messages.

推送失败日志会显示异常类型、HTTP 状态码及处理提示。例如 401 提示 API Key 无效，403 提示账户写入权限不足，连接失败或超时分别说明原因。待重试失败只记录一次汇总；意外异常保留一次 traceback。POST 错误消息不包含密钥、请求头、完整响应或邮件正文。

## Backfill and recovery / 历史补抓与故障恢复

Edit `.env` yourself after registering a famLedger account and creating its personal API Key:

注册账号并创建个人 API Key 后，自行填写 `.env`：

```dotenv
FAMLEDGER_API_URL=http://host.docker.internal:8888
FAMLEDGER_API_TOKEN=your-new-personal-api-key
MAILBRIDGE_PULL_ENABLED=true
MAILBRIDGE_POST_ENABLED=true
# Days, not transaction count / 单位是天，不是笔数
LOOKBACK_DAYS_CREDIT=3000
LOOKBACK_DAYS_DEBIT=3000
MAILBRIDGE_SYNC_INTERVAL_SECONDS=600
# Leave empty normally; use 10d@20261004-1 or all@20261004-1 for a manual replay.
# 平时留空；重推过去 10 天填 10d@20261004-1，全部缓存填 all@20261004-1。
MAILBRIDGE_REPLAY=
```

Apply environment changes / 应用配置：

```bash
docker compose up -d --force-recreate
```

Pull and POST are independent. With `PULL=true, POST=false`, mail is cached without contacting famLedger or changing delivery/replay states. With `PULL=false, POST=true`, pending and failed local mail is delivered without Microsoft network requests. With both `true`, both stages run; with both `false`, the task is paused. The same interval applies to either mode. Missing POST credentials are reported but do not stop an enabled mail pull. `--cached-only` also respects the POST switch and never fetches mail.

拉取和 POST 独立控制：`PULL=true、POST=false` 只抓取并缓存邮件，不请求 famLedger、不改推送及重推状态；`PULL=false、POST=true` 只补推本地待推和失败邮件，不请求微软。都为 `true` 时正常拉取并推送，都为 `false` 时暂停任务。各模式均使用同一个轮询间隔。POST 凭证缺失会记录错误，已开启的拉取仍会执行。`--cached-only` 同样遵守 POST 开关，始终不拉取邮件。上述 `PULL`、`POST` 对应完整变量名 `MAILBRIDGE_PULL_ENABLED`、`MAILBRIDGE_POST_ENABLED`；旧总开关已移除。

- Template defaults: 20 days. Changing either lookback value re-scans that folder once, then resumes incremental synchronization. The last successfully applied setting is persisted in SQLite, so `3000 → 50 → 3000` re-scans on each change. Existing cached bodies and successful deliveries are preserved; cached mail is not downloaded again.
- If famLedger is offline or its Key is rejected, the current batch stops POST attempts, keeps undelivered mail queued and continues caching new Microsoft mail. Delivery resumes in a later cycle after service/credentials recover.
- If Mailbridge is down for several days, its saved delta cursor catches up after restart, including missed mail older than the initial lookback window. If Microsoft expires the cursor, the folder is re-scanned. Microsoft authorization may need renewal.
- To replay already acknowledged mail, set `MAILBRIDGE_REPLAY=10d@20261004-1` for the past 10 days, or `MAILBRIDGE_REPLAY=all@20261004-1` for all cached history. Change the marker after `@` for another replay. Keep the value unchanged until the replay finishes: a restart resumes pending items and does not reset successful items again. A different target URL or API Key also gets its own delivery state.
- A day is 24 hours. The transaction-time window is fixed when the worker starts this operation and persists across retries. A recent email containing older transactions only replays transactions in that window. Normal failed and pending mail is still retried without a date limit. Increase the relevant lookback first if the required mail has not been cached.
- An interruption between a successful POST and its local acknowledgement is safe to retry: stable `external_id` lets famLedger acknowledge duplicates without overwriting them. A mail with several transactions is acknowledged only after all POSTs succeed.

模板默认回看各 20 天，每轮完成后默认等待 600 秒。修改天数为 3000 表示扫描过去 3000 **天**的可解析银行邮件，实际笔数取决于邮件内容。配置数值变动后重新扫描一次，再恢复增量同步；例如 `3000 → 50 → 3000` 每次变动都会重扫。缩小范围不会删除已缓存邮件和已导入交易，重扫也不会重置成功推送记录；不需要删数据库或手动删增量标记。

日志中的 `mode=history` 表示历史扫描，`mode=incremental` 表示增量扫描；`listed`/`fetched` 是读取的邮件元数据数量，`cached` 是新增缓存邮件，`already_cached` 是已有缓存，`outside_window` 是超出历史回看范围，`ignored` 是删除通知或不符合银行/标题筛选条件的邮件。最后的 `processed` 是成功处理的待推邮件数，`created` 是新建交易数，均为 0 时不代表没有扫描邮箱。

历史扫描使用 `Prefer: odata.maxpagesize=100` 设置每页大小，并跟随全部 `@odata.nextLink`；不使用可能截断个人邮箱历史结果的 `$top=100`。此前受截断影响的扫描进度会自动重建一次，已有缓存和成功推送记录保留。 / Historical scans use a page-size header and follow every nextLink. Existing checkpoints from capped scans are rebuilt once without resetting cached mail or successful deliveries. [Microsoft Graph message synchronization](https://learn.microsoft.com/en-us/graph/delta-query-messages).

famLedger 中断时，邮件会继续缓存，推送失败的邮件会保留在待推队列，服务恢复后自动补推。Mailbridge 中断几天时，重启后根据保存的增量进度补齐停机期间邮件；微软登录过期则需重新登录。

重推过去 10 天交易时，设置 `MAILBRIDGE_REPLAY=10d@20261004-1`；全部本地历史用 `MAILBRIDGE_REPLAY=all@20261004-1`。再次重推时改成新的标记，例如 `10d@20261004-2`，应用配置即可。同一值只触发一次，中途重启会续传；留空关闭手动重推。

`MAILBRIDGE_REPLAY` respects both switches: POST disabled defers replay without recording or consuming its marker; POST enabled starts or resumes it. PULL disabled means replay uses only SQLite, with no Microsoft requests. The range is fixed when POST first executes the marker, not when `.env` is edited. Normal pending and failed mail is delivered independently of the replay range.

`MAILBRIDGE_REPLAY` 遵守两个开关：POST 关闭时不执行、不记录或消耗重推标记，开启后才开始或续传；PULL 关闭时只重推 SQLite 缓存，不请求微软。过去 N 天的范围在 POST 首次执行该标记时固定，不是在编辑 `.env` 时固定。正常待推、失败邮件仍独立补推，不受手动重推范围限制。

天数按交易发生时间筛选，一天按 24 小时计算，时间范围在任务首次执行时固定并存入 SQLite。新收到的账单中夹有更早交易时，只重推时间范围内的交易；正常待推和失败邮件仍然全部重试，不受该范围限制。所需邮件尚未缓存时，应先增大对应 `LOOKBACK_DAYS_*` 补抓历史。若同时设置 3000 天，则先补抓历史邮件再在后续处理队列中完成推送。

Only mail still present in the configured Microsoft folders, or already stored in local SQLite, can be recovered. Bank notifications are not a complete banking history; missing/deleted emails cannot be invented. / 能恢复的范围是微软指定文件夹中仍保留的邮件及本地已缓存邮件；银行未发送、已经删除且本地未缓存的记录无法从邮件恢复。保留 `data/`，普通重启不要删除该目录。

## Backend layout / 后端结构

- `backend/config.py`: shared environment and logging configuration / 统一环境与日志配置。
- `backend/worker.py`: scheduler and cached-only command / 定时任务与本地缓存重试入口。
- `backend/auth/`: Microsoft authentication, token state and the simple web interface / 微软认证、授权状态及网页接口。
- `backend/ingest/`: Graph delta fetch, SQLite cache, bank parsers and famLedger delivery / 增量抓取、邮件缓存、解析和推送。
- `requirements.txt`: service dependencies / 服务依赖；Dockerfile lives at the service root.

## Operations / 启停与测试

```bash
docker compose logs --tail=100 mail-worker
docker compose restart
# Retry cached mail without Microsoft / 仅重试本地缓存，不请求微软：
docker compose run --rm --no-deps mail-worker python -m backend.worker --cached-only
docker compose down
# After editing .env, recreate containers / 修改 .env 后重新创建容器：
docker compose up -d --force-recreate
```

Host execution / 宿主机运行：

```bash
python -m pip install -r requirements.txt
# Host execution uses http://localhost:8889 as FAMLEDGER_API_URL.
python -m uvicorn backend.auth.web:app --host 127.0.0.1 --port 8502
# Run the scheduler in another terminal / 另一终端运行调度器：
python -m backend.worker
```

Tests / 测试：

```bash
python -m pip install pytest httpx
python -m pytest tests -q
```
