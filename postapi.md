# POST API 清单

核对时间：2026-10-03 01:11:27 CST。

当前主应用源码共有 **41 个处理函数、48 个 POST 路径**。下面列出全部显式 POST 业务路由，包括末尾斜杠入口与别名。所有主应用路由已按 `backend/main.py` 的 `/api` 挂载前缀展开。

这是接口目录；仅执行源码扫描和 GET `/openapi.json` 核对，没有为编写本文调用任何 POST 接口。

## 认证与请求格式

- “会话/个人 API Key”表示认证入口接受登录 Cookie、`X-Api-Key` 或 `Authorization: Bearer <个人 API Key>`；调用后仍会检查用户角色、家庭归属及具体账户权限。
- 系统账单服务凭证在当前源码中仅允许账户查询及流水导入/查询；POST 业务只允许 `/api/v1/transactions`，不能据此调用其他管理接口。
- 携带登录 Cookie 的写请求还需通过 CSRF 校验：同源 `Origin`，或在没有 `Origin` 时发送 `X-Famledger-CSRF: 1`。跨源请求仍会被拒绝。
- 除头像外，有请求体的接口均使用 JSON；表中的模型名对应源码中的 Pydantic 请求模型。路径中的 `{...}` 是路径参数。
- 末尾 `/` 的显式入口与同表所列无斜杠入口是同一处理函数；不把框架可能产生的重定向另计为业务路由。

## 主应用 POST 接口

### 账号与认证

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/auth/register` | 注册本地用户 | JSON：`RegisterRequest` | 公开；注册规则仍由后端校验 | `backend/auth.py` |
| `/api/auth/login` | 用户名与密码登录，设置会话 Cookie | JSON：`LoginRequest` | 公开 | `backend/auth.py` |
| `/api/auth/logout` | 退出当前会话并撤销该会话 | 无请求体 | 读取当前 Cookie；可重复退出 | `backend/auth.py` |
| `/api/auth/forgot-password/question` | 取得账户的密码找回安全问题 | JSON：`ForgotPasswordQuestionRequest` | 公开；有请求频率限制 | `backend/auth.py` |
| `/api/auth/forgot-password/reset` | 校验安全答案后重置密码 | JSON：`ForgotPasswordResetRequest` | 公开；必须通过安全答案校验 | `backend/auth.py` |
| `/api/auth/avatar` | 上传当前用户头像 | multipart/form-data：`file` | 登录会话 | `backend/auth.py` |

### 洞察提醒

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/insights/alerts/dismiss` | 忽略指定消费洞察提醒 | JSON：`DismissAlertRequest` | 登录会话 | `backend/routes/insights.py` |
| `/api/insights/alerts/{series_key}/ack` | 确认已知晓指定消费洞察提醒 | 无请求体；查询参数 `alert_type`，默认 `price_step` | 登录会话 | `backend/routes/insights.py` |

### 账户

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/accounts`<br>`/api/v1/accounts/` | 新建账户；非零初始余额自动生成期初活动 | JSON：`AccountCreate` | 会话/个人 API Key | `backend/routes/v1_accounts.py` |
| `/api/v1/accounts/{account_id}/transfer-ownership` | 将账户所有权转给同家庭成员 | JSON：`TransferOwnershipIn` | 会话/个人 API Key；账户管理权限 | `backend/routes/v1_accounts.py` |
| `/api/v1/accounts/{account_id}/reconcile-balance` | 账户“新建余额”/对账，生成差额活动 | JSON：`ReconcileBalanceIn` | 会话/个人 API Key；账户写权限 | `backend/routes/v1_accounts.py` |

### 流水

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/transactions`<br>`/api/v1/transactions/` | 录入一笔流水，支持账单导入与自动撮合 | JSON：`TransactionIn`；支持 `{ "transaction": {...} }` 包装 | 会话/个人 API Key；账户写权限；允许已绑定的账单服务凭证 | `backend/routes/v1_transactions.py` |
| `/api/v1/transactions/{transaction_id}/split` | 将一笔流水拆分成多个分类子项 | JSON：`SplitPayload` | 会话/个人 API Key；账户写权限 | `backend/routes/v1_transactions.py` |

### 转账

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/transfers`<br>`/api/v1/transfers/create` | 创建内部转账，生成转出、转入两笔流水及配对记录 | JSON：`TransferCreatePayload` | 会话/个人 API Key；两侧账户均可写 | `backend/routes/v1_transfers.py` |
| `/api/v1/transfers/{transfer_id}/reject` | 解除转账配对，并记录驳回以避免再次自动配对 | 无请求体 | 会话/个人 API Key；所涉账户写权限 | `backend/routes/v1_transfers.py` |
| `/api/v1/transfers/manual-pair` | 手动配对两笔现有流水为转账 | JSON：`ManualPairPayload` | 会话/个人 API Key；两侧账户均可写 | `backend/routes/v1_transfers.py` |

### 退款

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/refunds/{refund_id}/allocate` | 指定退款冲抵的原消费及金额 | JSON：`RefundAllocationCreate` | 会话/个人 API Key；退款与原消费账户均可写 | `backend/routes/v1_refunds.py` |
| `/api/v1/refunds/{refund_id}/link/{original_id}` | 将退款关联到指定原消费 | 无请求体；可选查询参数 `allocated_amount` | 会话/个人 API Key；退款与原消费账户均可写 | `backend/routes/v1_refunds.py` |
| `/api/v1/refunds/{refund_id}/unlink` | 解除退款关联及冲抵分配 | 无请求体 | 会话/个人 API Key；退款账户写权限 | `backend/routes/v1_refunds.py` |

### 分类

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/categories`<br>`/api/v1/categories/` | 创建消费或收入分类 | JSON：`CategoryCreate`；支持 `{ "category": {...} }` 包装 | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_categories.py` |

### 标签

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/tags`<br>`/api/v1/tags/` | 创建标签，或恢复已有归档标签 | JSON：`TagCreate` | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_tags.py` |

### 规则

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/rules`<br>`/api/v1/rules/` | 创建自动清洗/分类规则 | JSON：`RuleCreate` | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_rules.py` |
| `/api/v1/rules/dry-run` | 预演规则，不修改历史流水 | JSON：`DryRunPayload` | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_rules.py` |
| `/api/v1/rules/apply-retroactive` | 将已启用规则应用到可写的历史流水 | 无请求体 | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_rules.py` |
| `/api/v1/rules/{rule_id}/apply` | 将指定规则应用到可写的历史流水 | 无请求体 | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_rules.py` |

### 借据与贷款

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/debts` | 创建个人借出/借入记录 | JSON：`PersonalDebtCreate` | 会话/个人 API Key；须有家庭空间 | `backend/routes/v1_debts.py` |
| `/api/v1/debts/{debt_id}/repay` | 记录个人借据还款 | JSON：`PersonalDebtRepay` | 会话/个人 API Key；记录创建者或管理者 | `backend/routes/v1_debts.py` |
| `/api/v1/debts/{debt_id}/write-off` | 核销个人借据 | 无请求体 | 会话/个人 API Key；记录创建者或管理者 | `backend/routes/v1_debts.py` |
| `/api/v1/loans`<br>`/api/v1/debts/loans` | 独立登记贷款，创建负债账户和贷款资料 | JSON：`LoanCreate` | 会话/个人 API Key；须有家庭空间 | `backend/routes/v1_debts.py` |

### 家庭与邀请

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/family/create` | 创建协作家庭组，并迁移当前用户数据 | JSON：`FamilyCreateRequest` | 会话/个人 API Key；还需满足退出原家庭条件 | `backend/routes/v1_family.py` |
| `/api/v1/family/leave` | 退出协作家庭并迁移到个人空间 | 无请求体 | 会话/个人 API Key；还需满足退出条件 | `backend/routes/v1_family.py` |
| `/api/v1/family/members/create` | 在当前家庭创建新的成员账号 | JSON：`CreateFamilyMemberRequest` | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_family.py` |
| `/api/v1/family/members/{user_id}/kick` | 将指定成员移出家庭 | 无请求体 | 会话/个人 API Key；家庭 owner 或系统 admin；目标校验 | `backend/routes/v1_family.py` |
| `/api/v1/family/members/{user_id}/reset-password` | 重置指定用户密码并使已有登录会话失效 | JSON：`ResetPasswordRequest` | 会话/个人 API Key；仅系统 admin | `backend/routes/v1_family.py` |
| `/api/v1/family/invitations` | 向现有用户发送协作家庭邀请 | JSON：`CreateInvitationRequest` | 会话/个人 API Key；协作家庭 owner 或系统 admin | `backend/routes/v1_family.py` |
| `/api/v1/family/invitations/{invitation_id}/accept` | 接受入组邀请并迁移数据 | 无请求体 | 会话/个人 API Key；受邀人本人 | `backend/routes/v1_family.py` |
| `/api/v1/family/invitations/{invitation_id}/reject` | 拒绝入组邀请 | 无请求体 | 会话/个人 API Key；受邀人本人 | `backend/routes/v1_family.py` |

### OIDC

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/auth/sso/providers` | 配置 OIDC 身份提供商 | JSON：`SSOProviderCreate` | 系统 admin；使用 require_admin_user 认证依赖 | `backend/routes/v1_oidc.py` |

### 预算

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/budgets/settings` | 保存家庭总预算、分类预算等设置 | JSON：`Dict[str, Any]` | 会话/个人 API Key；家庭 owner 或系统 admin | `backend/routes/v1_budgets.py` |

### API Key

| POST 路径（同一行内为同一函数） | 用途 | 请求体/查询参数 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/api-keys` | 创建个人 API Key；完整密钥只返回一次 | JSON：`ApiKeyCreateRequest` | 登录会话；明确禁止个人 API Key 调用 | `backend/routes/v1_api_keys.py` |
| `/api/v1/api-keys/revoke-all` | 撤销当前用户全部个人 API Key | 无请求体 | 登录会话；明确禁止个人 API Key 调用 | `backend/routes/v1_api_keys.py` |

### 自动转账与贷款计划

| POST 路径 | 用途 | 请求体 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/plans/preview` | 创建前预览计划及还款明细 | `PlanInput` | 登录会话；校验关联账户权限 | `backend/routes/v1_schedules.py` |
| `/api/v1/plans` | 创建转账或贷款计划 | `PlanInput` | 登录会话；校验关联账户权限 | `backend/routes/v1_schedules.py` |
| `/api/v1/plans/{plan_id}/preview` | 编辑前预览未执行期次 | `PlanInput` | 登录会话；计划写权限 | `backend/routes/v1_schedules.py` |
| `/api/v1/plans/{plan_id}/occurrences/{number}` | 入账、跳过、撤销或关联银行流水 | `ActionInput` | 登录会话；计划写权限 | `backend/routes/v1_schedules.py` |
| `/api/v1/plans/{plan_id}/prepay` | 提前还款并调整后续计划 | `PrepayInput` | 登录会话；计划写权限 | `backend/routes/v1_schedules.py` |

### 待换汇流水

| POST 路径 | 用途 | 请求体 | 认证与权限 | 源码 |
|---|---|---|---|---|
| `/api/v1/pending-transactions/{row_id}/retry` | 重新取得交易日期汇率并尝试入账 | 无 | 会话/个人 API Key；账户写权限 | `backend/routes/v1_pending_fx.py` |
| `/api/v1/pending-transactions/{row_id}/confirm` | 根据银行实际结算金额入账 | `SettlementConfirmation` | 会话/个人 API Key；账户写权限 | `backend/routes/v1_pending_fx.py` |
| `/api/v1/pending-transactions/{row_id}/cancel` | 取消尚未入账的来源记录 | 无 | 会话/个人 API Key；账户写权限 | `backend/routes/v1_pending_fx.py` |

## 普通账户创建与独立贷款登记的区别

以下两个 POST 入口执行不同函数：

- `POST /api/v1/accounts`：请求模型为 `AccountCreate`，初始余额字段是 `balance`。当前代码调用 `_ensure_opening_balance_transaction`，非零期初余额会生成活动记录。
- `POST /api/v1/debts/loans`（别名 `/api/v1/loans`）：请求模型为 `LoanCreate`，字段为 `original_principal` 和可选 `current_balance`。当前代码写入账户余额和贷款本金，但没有调用上述期初活动生成方法；这是本次 B07 复测涉及的入口。

普通账户创建示例：

```http
POST /api/v1/accounts
Content-Type: application/json

{"name":"贷款账户示例","account_type":"loan","currency":"CNY","balance":"1000"}
```

独立贷款登记示例：

```http
POST /api/v1/debts/loans
Content-Type: application/json

{"name":"贷款登记示例","original_principal":"1000","current_balance":"1000","currency":"CNY","start_date":"2026-10-03"}
```

以上仅为请求格式示例，需要附带相应认证凭证及 CSRF 信息；编写本清单时没有发送这些示例请求。

## 独立账单界面的 POST 接口

下面 5 个接口定义在 `services/bill/front/main.py` 的独立 FastAPI 应用中，没有通过 `backend/main.py` 挂载到主应用；不要当作 8888 主应用接口。此处仅按源码列出，未启动或调用该独立服务。

| POST 路径 | 用途 | 请求格式 | 源码 |
|---|---|---|---|
| `/api/config` | 保存账单界面用户配置 | JSON 配置对象 | `services/bill/front/main.py` |
| `/api/categories` | 保存账单分类规则并清空规则缓存 | JSON 分类规则数据 | `services/bill/front/main.py` |
| `/api/remark/{tx_id}` | 修改账单记录备注 | JSON：`RemarkUpdate`，字段 `remark` | `services/bill/front/main.py` |
| `/api/auth/initiate` | 发起 Microsoft Graph 设备码授权流程 | 无请求体 | `services/bill/front/main.py` |
| `/api/records` | 手工新增旧账单表记录 | JSON：`BillRecord`，必填 `costtime`、`cost`、`account`、`behaviour`、`business`；可选 `remark` | `services/bill/front/main.py` |

这些独立路由函数未声明主应用的登录/个人 API Key 认证依赖；此清单不代表对独立服务实际部署与访问权限的安全审计。


## 多币种入账补充（B08/B09/B10）

新建交易的 `amount/currency` 为原币输入；返回的 `amount/currency` 为固定账户入账。可同时提供 `original_amount/original_currency` 明确原币。银行已知结算时提供 `settlement_amount/settlement_currency`；副卡还可提供 `master_settlement_amount/master_settlement_currency`。不得将预估转换数字作为银行实际金额。来源 `external_id` 与账户共同去重。

活动与交易列表用 `original_amount/original_currency` 展示原消费；旧记录缺失原币时保留已知入账金额并标为待核对。单笔详情额外返回 `display_amount/display_currency`（用户设置币种）及 `display_exchange_rate`、`display_exchange_rate_base_currency`、`display_exchange_rate_date`、`display_exchange_rate_source`。展示金额由固定入账按交易日期换算，不写回流水或余额。汇率获取失败时详情仍可读，`display_amount=null`、`display_money_error` 提供原因；前端不得将入账数字直接标为设置币种。编辑金额继续使用固定入账和原币字段。

汇率暂不可用时返回 `status=pending_fx` 和待换汇记录 ID，表示已保存、尚未入账。重复来源返回相同记录并带 `duplicate=true`。`canceled` 表示来源已取消，`posted` 表示待换汇已完成入账，`posted_transaction_id` 指向正式流水。调用方不得把 pending_fx/canceled 计为已入账。

退款关联的 `allocated_amount` 是原消费原币额度。不同原币需明确传 `original_currency` 和 `refund_original_amount`；同原币两边数量须相等。返回分配元数据含原消费固定入账冲抵、实际退款到账与汇差。`refund_info.remaining_amount` 和 `is_fully_allocated` 按原币计算，不应与账户入账金额比较。
