import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, ChevronDown, Info, Menu } from 'lucide-react';

export default function SureMoneyInOut({
  data,
  currencySymbol = '¥',
}) {
  const navigate = useNavigate();

  const periodLabel = data?.period_label || '2026年09月01日 to 2026年09月27日';
  const monthLabel = data?.month_label || '2026年09月';
  const balance = data?.balance ?? -2160.48;
  const income = data?.income ?? 590.86;
  const expenses = data?.expenses ?? 2751.34;
  const last6Months = data?.last_6_months || [
    { month: '4月', income: 0, expense: 0 },
    { month: '5月', income: 0, expense: 0 },
    { month: '6月', income: 0, expense: 0 },
    { month: '7月', income: 0, expense: 0 },
    { month: '8月', income: 2553.25, expense: 196.31 },
    { month: '9月', income: 590.86, expense: 2751.34 },
  ];

  // Calculate bar heights
  const maxVal = Math.max(
    ...last6Months.map((m) => Math.max(m.income, m.expense)),
    100
  );

  return (
    <div className="space-y-4 pt-1">
      {/* ── 1. Date Range Subtitle (Exact 11.jpg) ── */}
      <p className="text-xs sm:text-sm text-zinc-500 dark:text-zinc-400 font-medium">
        {periodLabel}
      </p>

      {/* ── 2. Filters Row: (i) 2026年09月 v | All accounts (Exact 11.jpg) ── */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/80 text-xs font-semibold text-zinc-800 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors"
        >
          <Info className="w-3.5 h-3.5 text-zinc-400" />
          <span>{monthLabel}</span>
          <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
        </button>

        <button
          type="button"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/80 text-xs font-semibold text-zinc-800 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors"
        >
          <Menu className="w-3.5 h-3.5 text-zinc-400" />
          <span>All accounts</span>
        </button>
      </div>

      {/* ── 3. Legend & Time Scope (Exact 11.jpg) ── */}
      <div className="flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400 pt-1">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span>Income</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-zinc-400 dark:bg-zinc-500" />
            <span>Expenses</span>
          </div>
        </div>
        <span className="text-[11px] text-zinc-400 font-medium">Last 6 months</span>
      </div>

      {/* ── 4. Bar Chart Area (Exact 11.jpg 6-Month Comparison) ── */}
      <div className="h-44 sm:h-48 pt-4 flex items-end justify-between gap-2 border-b border-zinc-100 dark:border-zinc-800/80 pb-2">
        {last6Months.map((m, idx) => {
          const incHeight = Math.max(0, (m.income / maxVal) * 120);
          const expHeight = Math.max(0, (m.expense / maxVal) * 120);

          return (
            <div key={idx} className="flex-1 flex flex-col items-center gap-2 group">
              {/* Bars container */}
              <div className="h-32 w-full flex items-end justify-center gap-1 sm:gap-1.5 relative">
                {/* Income bar (Green) */}
                {m.income > 0 && (
                  <div
                    style={{ height: `${incHeight}px` }}
                    className="w-2 sm:w-2.5 bg-emerald-500 rounded-t-sm transition-all group-hover:brightness-110"
                    title={`${m.month} 收入: ${currencySymbol}${m.income.toFixed(2)}`}
                  />
                )}
                {/* Expense bar (Grey, like 11.jpg) */}
                <div
                  style={{ height: `${Math.max(4, expHeight)}px` }}
                  className={`w-3.5 sm:w-5 rounded-t-md transition-all group-hover:brightness-110 ${
                    m.expense > 0
                      ? 'bg-zinc-400 dark:bg-zinc-500'
                      : 'bg-zinc-100 dark:bg-zinc-800'
                  }`}
                  title={`${m.month} 支出: ${currencySymbol}${m.expense.toFixed(2)}`}
                />
              </div>

              {/* Month label */}
              <span className="text-[11px] sm:text-xs font-medium text-zinc-500 dark:text-zinc-400">
                {m.month}
              </span>
            </div>
          );
        })}
      </div>

      {/* ── 5. Current Month Summary & Balance (Exact 11.jpg) ── */}
      <div className="pt-2 space-y-3">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
          {monthLabel}
        </h3>

        <div className="flex items-center justify-between py-1 text-sm font-semibold">
          <span className="text-zinc-700 dark:text-zinc-300">Transaction balance</span>
          <span
            className={`font-mono text-base font-bold ${
              balance < 0 ? 'text-red-500 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'
            }`}
          >
            {balance < 0 ? '-' : '+'}{currencySymbol}{Math.abs(balance).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </span>
        </div>

        {/* Clickable Income & Expense Rows (Exact 11.jpg) */}
        <div className="space-y-2">
          {/* Income Row */}
          <button
            type="button"
            onClick={() => navigate('/transactions?transaction_type=income')}
            className="w-full flex items-center justify-between p-3.5 rounded-xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-850 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors group"
          >
            <div className="flex items-center gap-2.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
              <span className="text-xs sm:text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                Income
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs sm:text-sm font-bold text-emerald-600 dark:text-emerald-400">
                {currencySymbol}{income.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </span>
              <ChevronRight className="w-4 h-4 text-zinc-400 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </button>

          {/* Expenses Row */}
          <button
            type="button"
            onClick={() => navigate('/transactions?transaction_type=expense')}
            className="w-full flex items-center justify-between p-3.5 rounded-xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-850 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors group"
          >
            <div className="flex items-center gap-2.5">
              <span className="w-2.5 h-2.5 rounded-full bg-zinc-400 dark:bg-zinc-500" />
              <span className="text-xs sm:text-sm font-semibold text-zinc-800 dark:text-zinc-200">
                Expenses
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs sm:text-sm font-bold text-zinc-900 dark:text-zinc-100">
                {currencySymbol}{expenses.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </span>
              <ChevronRight className="w-4 h-4 text-zinc-400 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
