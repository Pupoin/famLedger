#### 问题 1：交易分类（Categories）的国际化处理策略
 策略 A（内置双语对照字典，推荐）：
  系统预设的常用分类使用国际化标识（如 category.food_dining）。切换为英文时，“餐饮美食”自动显示为“Dining
  & Food”；而用户自己手动新建的分类，录入什么就显示什么。

  #### 问题 2：多币种与汇率更新来源（离线 vs 在线）
  既然我们要保证系统在内网稳定、低资源运行，如果家庭涉及多币种（如美股账户 USD、招行卡 CNY、港币卡
  HKD）：

  • 策略 A（每天定时拉取 + 离线缓存，推荐）：
  后台每天凌晨自动从免费公开汇率源拉取一次最新中间价并缓存在本地数据库；若内网断网，自动沿用最后一次本地
  缓存汇率。


  #### 问题 3：招行账单自动化工具（sure/bill）的代码与容器归宿 
 
  既然系统整体改名为 FamLedger： 
代码收进 FamLedger 单仓库，但 bill 保持独立服务，通过正式 API 与 FamLedger 通信。
但 famledger-bill 不要直接读 FamLedger PostgreSQL，也不要调用 Backend 内部代码，只认：
FAMLEDGER_API_URL=http://backend:3000
FAMLEDGER_API_TOKEN=...