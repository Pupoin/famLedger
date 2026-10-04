# famLedger 文档

只保留当前可用于开发、部署和业务核对的说明。早期改造草案、已完成的修复记录和旧迁移方案已清理；当前实现以源码与回归测试为准。

| 文档 | 用途 |
| --- | --- |
| [项目 README](../README.md) | 本地开发、Docker、依赖安装与测试 |
| [现金流与桑基图](./CASHFLOW_SANKEY_SPEC.md) | 收支、退款、内部转账与图表口径 |
| [POST 接口](../postapi.md) | 写入接口、身份认证与来源流水 ID |
| [账单服务](../services/bill/README.md) | 邮件账单调度、解析与同步 |

业务金额的实现与验证主要位于 `backend/services/stats_engine.py`、`booking_money.py`、`refund_money.py`、`schedules.py` 和 `backend/tests/`。前端显示币种与语言偏好由 `frontend/src/UserPreferencesContext.jsx` 管理。
