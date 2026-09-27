import { useState, useEffect } from "react";
import { useUsers } from "../ConfigContext";
import { useIncomeMode } from "../hooks/useIncomeMode";

const SECTIONS = [
  {
    id: "overview",
    icon: "home",
    title: "系统概览与模式",
    content: (mode, incomeEnabled) => [
      "famLedger 是一套对齐 Sure 现代化设计的高性能家庭财务与资产管理系统。系统深度整合邮件智能账单解析、双轨收支流水、资金流向桑基图（Sankey）、消费日历热力图、退款冲抵与转账仲裁引擎。",
      `当前系统运行模式为：**${mode === "personal" ? "单人模式 (Personal)" : mode === "blended" ? "混合模式 (Blended)" : "共享分摊模式 (Shared)"}**。您可以在「系统设置」中自由调整运行模式。`,
      "### 三种记账协作模式说明",
      "**单人模式 (Personal)** — 专为个人设计，全面记录个人资产负债、收支明细与预算投资情况。",
      "**共享分摊模式 (Shared)** — 专为伴侣或家庭成员设计，所有公共账单默认按比例分摊，实时计算双方结算余额（Balance）与待结算款项。",
      "**混合模式 (Blended)** — 既包含个人独立账目，又包含家庭公共开支，支持单笔交易灵活标记为“个人”或“50/50 分摊”。",
    ],
  },
  {
    id: "dashboard",
    icon: "dashboard",
    title: "资产总览 (仪表盘)",
    content: (mode, incomeEnabled) => [
      "资产总览看板对齐 Sure 现代财务可视化规范，全方位呈现实时财务全景：",
      "### 1. 现金流流动图 (Sankey Diagram)",
      "左侧接入**各项真实收入**（如工资收入、投资收益），通过中间**现金流枢纽 (Cash Flow)** 平滑分流至右侧各大**支出消费分类**。点击任意分类可直接跳转穿透至对应的交易流水列表。",
      "### 2. 支出环形图与分类排行榜",
      "左侧圆环展示**本期净支出总额**，右侧清晰列出各大分类的真实支出金额与占比。点击饼图扇区或分类行，一键过滤查看该分类的消费明细；底部更包含真实的**待匹配退款调整**净额扣除项。",
      "### 3. 消费日历热力图 (Spending Heatmap)",
      "按星期一至星期日展示长达数月的每日消费密度矩阵。单元格色块深浅严格对应真实当日支出或退款，点击任意格子可直接弹出查看该日所有交易流水；PC 与移动端自适应排布，支持平滑横向滚动。",
      "### 4. 资产负债表与净资产",
      "汇聚各银行账户、信用卡与贷款借记资产，实时动态计算个人与家庭总资产、总负债及净资产（Net Worth）。",
    ],
  },
  {
    id: "transactions",
    icon: "credit_card",
    title: "交易明细与对账",
    content: (mode, incomeEnabled) => [
      "交易明细页是系统的核心对账与流水中心，支持极速虚拟滚动与双向仲裁：",
      "### 1. 账单分组与平台标识",
      "流水按日期智能分组，清晰标明当日入账笔数与当日净变动金额。商户左侧直观呈现专属彩色品牌徽标（如绿底「财」微信支付、蓝底「支」支付宝、红底「抖」抖音支付、蓝底「G」Google 等）。",
      "### 2. 退款冲抵与锁定机制",
      "系统智能关联退款与其原始扣款交易。已冲抵退款带有安全锁扣标签（如 `↺ 退款 🔒 ¥12.15`）。在交易详情抽屉中，您可以手动搜索并解除冲抵或绑定指定原消费，消除重复记账。",
      "### 3. 内部转账仲裁",
      "支持将不同账户间的充值、还款、提现记录撮合为内部转账（Transfer），自动从收支统计中剔除，避免重复虚高收支规模。支持多选批量撮合与快速解绑。",
      "### 4. 快捷批量操作",
      "支持单选或按住 Shift 多选交易流水，底部弹出快捷操作悬浮栏，可批量打标签、批量修改分类或批量执行转账仲裁。",
    ],
  },
  {
    id: "analytics",
    icon: "bar_chart",
    title: "统计报表与分析",
    content: (mode, incomeEnabled) => [
      "报表中心提供深度多维度的数据洞察与趋势推演：",
      "### 1. 周期筛选与核心 KPI",
      "支持「本月 (MTD)」、「近30天 (30D)」、「本年 (YTD)」与「全部 (ALL)」快捷切换，以及月份时间滑块。卡片实时呈现总支出、净储蓄、储蓄率与日均支出。",
      "### 2. 支出结构与待匹配退款调整",
      "展示完整分类支出排行与占比。当期如果产生跨期退款或超额退款，系统自动列出“待匹配退款调整”，并在总支出中合规扣减。",
      "### 3. 现金流瀑布流",
      "以瀑布柱状图呈现总收入、各大支出项、退款回冲与最终净现金流余额的流转过程。",
      "### 4. 投资矩阵与收益分析",
      "呈现家庭投资持仓总市值、各资产配置比例及累计历史收益波动。",
    ],
  },
  {
    id: "budget",
    icon: "map",
    title: "预算管理",
    content: () => [
      "预算中心帮助您合理规划每月各项开支，防止意外超支：",
      "### 1. 分类预算配额",
      "可为每个消费分类（如餐饮美食、超市便利、生活缴费等）设定每月消费上限。",
      "### 2. 实时进度与预警",
      "进度条动态反映当前分类已花费金额、剩余可用额度及消耗百分比。接近或超出限额时自动高亮警示。",
      "### 3. 总预算聚合",
      "顶部清晰汇总本月总预算、当前已用预算总额与剩余可支配自由资金。",
    ],
  },
  {
    id: "emails",
    icon: "inbox",
    title: "账单信箱与解析",
    content: () => [
      "账单邮件智能导入与审查中心：",
      "### 1. 自动同步与智能提取",
      "系统后台自动监听并抓取各大银行（如招商银行、中国银行等）的消费通知邮件，AI 引擎精准抽取交易时间、商户全称、外币与人民币金额、卡号尾号。",
      "### 2. 原始邮件正文比对",
      "点击任意解析条目，右侧弹窗同时展示**解析提取结果**与**原始邮件纯文本/HTML 邮件原文**，账单细节清晰可验，杜绝虚假解析。",
      "### 3. 错误修正与重新解析",
      "如发现银行模板变动或解析异常，可直接在抽屉中点击「重新解析」重新提取。",
    ],
  },
  {
    id: "rules",
    icon: "tune",
    title: "规则引擎与自动化",
    content: () => [
      "通过高度可定制的规则，让繁杂的账目分类自动化运行：",
      "### 1. 条件匹配",
      "支持根据商户名称关键词、交易描述文本、金额区间或交易账户设置触发条件（包含、等于、正则匹配等）。",
      "### 2. 自动动作",
      "命中规则后自动执行：重命名商户名称为规范商户、自动归纳到指定消费分类、自动追加标签（如 #商务报销、#家庭聚会）。",
      "### 3. 规则优先级与测试",
      "支持拖拽调整规则执行先后顺序，并可对单笔历史交易进行实时匹配测试。",
    ],
  },
  {
    id: "settings",
    icon: "settings",
    title: "系统设置与安全",
    content: () => [
      "管理您的账户、系统集成与安全偏好：",
      "### 1. OIDC 单点登录集成 (SSO)",
      "支持配置标准 OpenID Connect 服务商（如 Authelia、Keycloak、Google、Authentik 等），实现一键安全免密登入系统。",
      "### 2. 语言与显示偏好",
      "支持简体中文（zh）与 English（en）实时双语切换；支持明亮浅色（Light）与暗黑深色（Dark）主题切换。",
      "### 3. 金额隐私模式 (Privacy Eye)",
      "点击导航栏右上角或面包屑旁的眼睛图标，一键将全站所有敏感金额脱敏打码，便于在公共场合或截图分享时使用。",
      "### 4. 数据备份与导出",
      "支持将全量财务交易流水一键导出为标准 CSV / Excel 表格，方便进行离线二次分析或长期存档。",
    ],
  },
];

function renderLine(line, i) {
  if (line.startsWith("### ")) {
    return (
      <h4
        key={i}
        className="text-sm font-bold text-zinc-900 dark:text-zinc-100 mt-4 mb-1"
      >
        {line.slice(4)}
      </h4>
    );
  }

  // Render bold segments marked with **...**
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return (
    <p key={i} className="text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed">
      {parts.map((part, j) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <span key={j} className="font-semibold text-zinc-900 dark:text-zinc-200">
            {part.slice(2, -2)}
          </span>
        ) : (
          part
        ),
      )}
    </p>
  );
}

export default function HelpModal({ onClose }) {
  const { mode } = useUsers();
  const { incomeEnabled } = useIncomeMode();
  const [activeSection, setActiveSection] = useState("overview");

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const section = SECTIONS.find((s) => s.id === activeSection) || SECTIONS[0];
  const lines = section.content(mode, incomeEnabled);
  const resolveTitle = (s) => typeof s.title === "function" ? s.title(mode, incomeEnabled) : s.title;

  return (
    <div
      className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-zinc-900 rounded-3xl shadow-2xl border border-zinc-200/80 dark:border-zinc-800 w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-6 pb-4 sm:p-8 sm:pb-4 border-b border-zinc-100 dark:border-zinc-800/80 flex items-start justify-between">
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-zinc-900 dark:text-zinc-100 tracking-tight">
              系统使用手册
            </h2>
            <p className="text-zinc-500 dark:text-zinc-400 text-xs sm:text-sm mt-1">
              深入了解 famLedger 资产管理系统的全部核心功能与操作技巧
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
            title="关闭窗口"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar nav */}
          <nav className="hidden sm:flex flex-col w-56 shrink-0 border-r border-zinc-100 dark:border-zinc-800/80 overflow-y-auto py-3 px-2 bg-zinc-50/50 dark:bg-zinc-900/50">
            {SECTIONS.map((s) => {
              const isActive = activeSection === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => setActiveSection(s.id)}
                  className={`flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-left text-xs sm:text-sm transition-all mb-1 ${
                    isActive
                      ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 font-semibold shadow-xs"
                      : "text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800/60 font-medium"
                  }`}
                >
                  <span
                    className="material-symbols-outlined text-[18px]"
                    style={
                      isActive
                        ? { fontVariationSettings: "'FILL' 1" }
                        : undefined
                    }
                  >
                    {s.icon}
                  </span>
                  <span className="truncate">{resolveTitle(s)}</span>
                </button>
              );
            })}
          </nav>

          {/* Mobile section selector */}
          <div className="sm:hidden w-full flex flex-col overflow-hidden">
            <div className="px-4 pt-2.5 pb-2.5 border-b border-zinc-100 dark:border-zinc-800 overflow-x-auto bg-zinc-50/50 dark:bg-zinc-900/50">
              <div className="flex gap-1.5 min-w-max">
                {SECTIONS.map((s) => {
                  const isActive = activeSection === s.id;
                  return (
                    <button
                      key={s.id}
                      onClick={() => setActiveSection(s.id)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs whitespace-nowrap transition-colors ${
                        isActive
                          ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 font-bold"
                          : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 font-medium"
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">
                        {s.icon}
                      </span>
                      {resolveTitle(s)}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Mobile content */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2">
              <div className="flex items-center gap-2 mb-2 pb-2 border-b border-zinc-100 dark:border-zinc-800">
                <span
                  className="material-symbols-outlined text-zinc-900 dark:text-white"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  {section.icon}
                </span>
                <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                  {resolveTitle(section)}
                </h3>
              </div>
              {lines.map((line, i) => renderLine(line, i))}
            </div>
          </div>

          {/* Desktop content */}
          <div className="hidden sm:flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto px-8 py-6 space-y-2">
              <div className="flex items-center gap-2.5 mb-4 pb-3 border-b border-zinc-100 dark:border-zinc-800/80">
                <span
                  className="material-symbols-outlined text-zinc-900 dark:text-zinc-100 text-[22px]"
                  style={{ fontVariationSettings: "'FILL' 1" }}
                >
                  {section.icon}
                </span>
                <h3 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
                  {resolveTitle(section)}
                </h3>
              </div>
              {lines.map((line, i) => renderLine(line, i))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 sm:p-5 border-t border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-900/50 flex justify-end">
          <button
            onClick={onClose}
            className="w-full sm:w-auto px-6 py-2.5 bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-100 text-white dark:text-zinc-900 font-semibold text-sm rounded-xl transition-colors shadow-xs"
          >
            我知道了
          </button>
        </div>
      </div>
    </div>
  );
}
