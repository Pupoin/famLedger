import { chartMoney } from '../../utils/chartMoney';
import { dateLabel, tx, useLocale, currentLocale } from "../../localization.js";
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { useCurrency } from '../../CurrencyContext';

export default function SureMoneyInOut({
  data,
  currencySymbol: reportSymbol,
  userFilter = '',
}) {
  const locale = useLocale();
  const compactRange = locale === 'en-US';
  const { symbol, privacyMode } = useCurrency() || {};
  const currencySymbol = reportSymbol ?? symbol ?? '';
  const formatAmount = value => chartMoney(value, currencySymbol, privacyMode, currentLocale());
  const navigate = useNavigate();
  const [trendRange, setTrendRange] = useState('6m');

  const periodLabel = data?.period_label || '';
  const startDate = data?.period_dates?.start;
  const endDate = data?.period_dates?.end;

  const balance = data?.balance ?? 0;
  const income = data?.income ?? 0;
  const expenses = data?.expenses ?? 0;

  const activeBars = trendRange === '12m'
    ? data?.last_12_months || data?.last_6_months || []
    : data?.last_6_months || [];

  // Calculate bar heights
  const maxVal = Math.max(
    ...activeBars.map((m) => Math.max(m.income, m.expense)),
    100
  );

  const handleIncomeClick = () => {
    const params = new URLSearchParams();
    params.set('transaction_type', 'income');
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') params.set('user', userFilter);
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    navigate(`/transactions?${params.toString()}`);
  };

  const handleExpenseClick = () => {
    const params = new URLSearchParams();
    params.set('transaction_type', 'expense');
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') params.set('user', userFilter);
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    navigate(`/transactions?${params.toString()}`);
  };

  const handleBalanceClick = () => {
    const params = new URLSearchParams();
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') params.set('user', userFilter);
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    navigate(`/transactions?${params.toString()}`);
  };

  const handleMonthBarClick = (m) => {
    const params = new URLSearchParams();
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') params.set('user', userFilter);
    if (m.start_date) params.set('start_date', m.start_date);
    if (m.end_date) params.set('end_date', m.end_date);
    navigate(`/transactions?${params.toString()}`);
  };

  return (
    <div className="space-y-4 pt-1">
      {/* ── 1. Legend & 6M / 12M Range Switcher ── */}
      <div className="flex items-center justify-between gap-2 text-xs text-zinc-500 dark:text-zinc-400">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 dark:bg-emerald-500" />
            <span className="font-medium text-zinc-700 dark:text-zinc-300">{tx("收入")}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-zinc-400 dark:bg-zinc-500" />
            <span className="font-medium text-zinc-700 dark:text-zinc-300">{tx("支出")}</span>
          </div>
        </div>

        <div data-testid="money-in-out-range" className="inline-flex shrink-0 p-0.5 bg-zinc-100 dark:bg-zinc-800 rounded-lg text-xs font-medium">
          <button
            type="button"
            aria-label={tx("近 6 个月")}
            title={tx("近 6 个月")}
            aria-pressed={trendRange === '6m'}
            onClick={() => setTrendRange('6m')}
            className={`${compactRange ? 'px-3 py-1.5' : 'px-2.5 py-1'} rounded-md whitespace-nowrap transition-all cursor-pointer ${
              trendRange === '6m'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >{compactRange ? '6M' : tx("近 6 个月")}</button>
          <button
            type="button"
            aria-label={tx("近 12 个月")}
            title={tx("近 12 个月")}
            aria-pressed={trendRange === '12m'}
            onClick={() => setTrendRange('12m')}
            className={`${compactRange ? 'px-3 py-1.5' : 'px-2.5 py-1'} rounded-md whitespace-nowrap transition-all cursor-pointer ${
              trendRange === '12m'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >{compactRange ? '12M' : tx("近 12 个月")}</button>
        </div>
      </div>

      {/* ── 2. Bar Chart Area (Clickable to jump into that month) ── */}
      <div data-testid="money-in-out-bars" className="h-44 sm:h-48 pt-3 flex items-end justify-between gap-0.5 sm:gap-2 border-b border-zinc-100 dark:border-zinc-800 pb-2 overflow-x-auto">
        {activeBars.map((m, idx) => {
          const incHeight = Math.max(0, (m.income / maxVal) * 120);
          const expHeight = Math.max(0, (m.expense / maxVal) * 120);
          const isLatest = idx === activeBars.length - 1;

          return (
            <div
              key={m.ym || idx}
              data-testid="money-in-out-month"
              data-start-date={m.start_date}
              data-end-date={m.end_date}
              onClick={() => handleMonthBarClick(m)}
              className="flex-1 min-w-[20px] sm:min-w-[28px] flex flex-col items-center gap-1.5 sm:gap-2 group cursor-pointer"
              title={tx("点击查看 {p0} 流水 (收入: {p1}{p2}, 支出: {p3}{p4})", {p0: (m.year_month || m.month), p1: '', p2: formatAmount(m.income), p3: '', p4: formatAmount(m.expense)})}
            >
              {/* Bars container */}
              <div className="h-32 w-full flex items-end justify-center gap-0.5 sm:gap-1 relative group-hover:scale-y-[1.03] transition-transform origin-bottom">
                {/* Income bar */}
                {m.income > 0 && (
                  <div
                    style={{ height: `${incHeight}px` }}
                    className="w-1.5 sm:w-2.5 bg-emerald-600 dark:bg-emerald-500 rounded-t-sm transition-all group-hover:brightness-110 shadow-2xs"
                  />
                )}
                {/* Expense bar */}
                <div
                  style={{ height: `${Math.max(4, expHeight)}px` }}
                  className={`w-2 sm:w-3.5 rounded-t-sm transition-all group-hover:brightness-110 ${
                    m.expense > 0
                      ? 'bg-zinc-400 dark:bg-zinc-500 shadow-2xs'
                      : 'bg-zinc-100 dark:bg-zinc-800/60'
                  }`}
                />
              </div>

              {/* Month label */}
              <span
                className={`text-[11px] sm:text-xs font-mono transition-colors whitespace-nowrap ${
                  isLatest
                    ? 'font-bold text-zinc-900 dark:text-zinc-100 underline decoration-emerald-500 underline-offset-4'
                    : 'text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-800 dark:group-hover:text-zinc-200'
                }`}
              >
                {dateLabel(m.month)}
              </span>
            </div>
          );
        })}
      </div>

      {/* ── 3. Current Period Summary & Balance (Clickable with period filters) ── */}
      <div className="pt-2 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 border-b border-zinc-100 dark:border-zinc-800/70 pb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{tx("当期收支结余")}</h3>
            {periodLabel && (
              <span className="text-xs font-mono text-zinc-500 dark:text-zinc-400 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded-md">
                {dateLabel(periodLabel)}
              </span>
            )}
          </div>

          <div
            onClick={handleBalanceClick}
            className="flex items-center gap-1.5 cursor-pointer hover:opacity-80 transition-opacity"
            title={tx("点击查看当期（{p0}）所有收支流水", {p0: (periodLabel)})}
          >
            <span
              className={`font-mono text-base font-bold ${
                balance < 0
                  ? 'text-rose-600 dark:text-rose-400'
                  : balance > 0
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : 'text-zinc-900 dark:text-zinc-100'
              }`}
            >
              {privacyMode ? '••••••' : `${balance < 0 ? '−' : balance > 0 ? '+' : ''}${formatAmount(Math.abs(balance))}`}
            </span>
            <ChevronRight className="w-4 h-4 text-zinc-400" />
          </div>
        </div>

        {/* Clickable Income & Expense Rows */}
        <div className="space-y-2">
          {/* Income Row */}
          <button
            type="button"
            onClick={handleIncomeClick}
            className="w-full flex items-center justify-between p-3.5 rounded-xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-800/80 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs transition-colors group cursor-pointer"
            title={tx("点击查看当期（{p0}）所有收入明细", {p0: (periodLabel)})}
          >
            <div className="flex items-center gap-2.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-600 dark:bg-emerald-500 shrink-0" />
              <span className="text-xs sm:text-sm font-semibold text-zinc-800 dark:text-zinc-200">{tx("收入")}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs sm:text-sm font-bold text-zinc-900 dark:text-zinc-100">
                {formatAmount(income)}
              </span>
              <ChevronRight className="w-4 h-4 text-zinc-400 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </button>

          {/* Expenses Row */}
          <button
            type="button"
            onClick={handleExpenseClick}
            className="w-full flex items-center justify-between p-3.5 rounded-xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-800/80 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-900 dark:text-zinc-100 shadow-2xs transition-colors group cursor-pointer"
            title={tx("点击查看当期（{p0}）所有支出明细", {p0: (periodLabel)})}
          >
            <div className="flex items-center gap-2.5">
              <span className="w-2.5 h-2.5 rounded-full bg-zinc-400 dark:bg-zinc-500 shrink-0" />
              <span className="text-xs sm:text-sm font-semibold text-zinc-800 dark:text-zinc-200">{tx("支出")}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-xs sm:text-sm font-bold text-zinc-900 dark:text-zinc-100">
                {formatAmount(expenses)}
              </span>
              <ChevronRight className="w-4 h-4 text-zinc-400 group-hover:translate-x-0.5 transition-transform" />
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
