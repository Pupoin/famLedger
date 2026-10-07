import { categoryLabel, tx, useLocale } from "../localization.js";
import React, { lazy, Suspense, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Printer, ChevronLeft, ChevronRight, ChevronDown, Download, ExternalLink, TrendingUp, TrendingDown, PieChart as PieIcon, Layers } from 'lucide-react';
import useReportData from '../hooks/useReportData';
import { useCurrency } from '../CurrencyContext';
import { formatCurrency } from '../utils/currency';
import { loadNetWorthChart } from '../utils/analyticsLoader';
import { combineReportSections } from '../utils/reportSections';
import CalendarDateInput from '../components/CalendarDateInput';
import { usePageViewState, usePageScrollRestoration } from '../PageViewContext';

const NetWorthChart = lazy(loadNetWorthChart);

function HistoryStatus({ error, onRetry }) {
  return error ? <div role="alert" className="p-5 text-sm text-rose-600 space-y-2">
    <p>{tx(error)}</p><button onClick={onRetry} className="px-3 py-2 rounded-lg border border-current">{tx('重试')}</button>
  </div> : <div role="status" className="p-5 text-sm text-zinc-500">{tx('正在加载历史走势…')}</div>;
}

export default function Analytics() {
  useLocale();
  const { t, i18n } = useTranslation();
  const { privacyMode, symbol, currency } = useCurrency();
  const isEn = (i18n.language || '').startsWith('en');

  // Period Preset
  const [period, setPeriod] = usePageViewState('period', 'monthly'); // 'monthly' | 'quarterly' | 'ytd' | '6m' | 'custom'

  const getInitialMonth = () => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  };

  const getInitialCustomDates = () => {
    const now = new Date();
    const y = now.getFullYear();
    const m = now.getMonth() + 1;
    const lastDay = new Date(y, m, 0).getDate();
    return {
      start: `${y}-${String(m).padStart(2, '0')}-01`,
      end: `${y}-${String(m).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`,
    };
  };

  const [selectedMonth, setSelectedMonth] = usePageViewState('selectedMonth', getInitialMonth);
  const [customStartDate, setCustomStartDate] = usePageViewState('customStartDate', () => getInitialCustomDates().start);
  const [customEndDate, setCustomEndDate] = usePageViewState('customEndDate', () => getInitialCustomDates().end);

  // Collapsible sections state
  const [sectionsOpen, setSectionsOpen] = usePageViewState('sectionsOpen', {
    trends: true,
    activity: true,
    netWorth: true,
    investments: true,
  });

  const toggleSection = (key) => {
    setSectionsOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const [retryCount, setRetryCount] = useState(0);
  const reportQuery = useMemo(() => {
    const params = new URLSearchParams({ period });
    if (period === 'custom') {
      if (customStartDate) params.set('start_date', customStartDate);
      if (customEndDate) params.set('end_date', customEndDate);
    } else {
      params.set('selected_month', selectedMonth);
    }
    return params.toString();
  }, [period, selectedMonth, customStartDate, customEndDate]);
  const { data: currentData, loading, error: loadError } = useReportData(
    `/api/v1/analytics/report?${reportQuery}&include_history=false`, currency, '无法加载报表', retryCount);
  const { data: historyData, loading: historyLoading, error: historyError } = useReportData(
    currentData ? `/api/v1/analytics/history?${reportQuery}` : null, currency, '无法加载报表', retryCount);
  const { data: reportData, historyReady } = useMemo(
    () => combineReportSections(currentData, historyData), [currentData, historyData]);
  const retry = () => setRetryCount(value => value + 1);
  const historyFailure = historyError || (historyData && !historyReady && !historyLoading ? '无法加载报表' : '');
  const fmt = (value) => privacyMode ? "••••" : formatCurrency(value, reportData?.currency_symbol || symbol);
  usePageScrollRestoration(!!reportData && (historyReady || !!historyFailure));

  // Format dynamic period title based on selected period and language
  const periodDisplay = useMemo(() => {
    const [y, m] = selectedMonth.split('-').map(Number);
    const enMonths = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    if (period === 'monthly') {
      return isEn ? `${enMonths[m - 1]} ${y}` : `${y}年${String(m).padStart(2, '0')}月`;
    }
    if (period === 'quarterly') {
      const q = Math.floor((m - 1) / 3) + 1;
      const startM = (q - 1) * 3 + 1;
      const endM = startM + 2;
      return isEn
        ? `Q${q} ${y} (${enMonths[startM - 1]} - ${enMonths[endM - 1]})`
        : `${y}年 Q${q} (${String(startM).padStart(2, '0')}月-${String(endM).padStart(2, '0')}月)`;
    }
    if (period === 'ytd') {
      return isEn
        ? `${y} This Year (Jan - ${enMonths[m - 1]})`
        : `${y} 今年 (01月-${String(m).padStart(2, '0')}月)`;
    }
    if (period === '6m') {
      const endD = new Date(y, m - 1, 1);
      const startD = new Date(y, m - 6, 1);
      const sY = startD.getFullYear();
      const sM = String(startD.getMonth() + 1).padStart(2, '0');
      const eY = endD.getFullYear();
      const eM = String(endD.getMonth() + 1).padStart(2, '0');
      return isEn
        ? `Last 6 Mos (${sY}/${sM} - ${eY}/${eM})`
        : `近半年 (${sY}/${sM} - ${eY}/${eM})`;
    }
    if (period === 'custom') {
      return isEn
        ? `${customStartDate} to ${customEndDate}`
        : `${customStartDate} 至 ${customEndDate}`;
    }
    return isEn ? `${enMonths[m - 1]} ${y}` : `${y}年${m}月`;
  }, [period, selectedMonth, customStartDate, customEndDate, isEn]);

  const formatMonthDisplay = (mRow) => {
    if (isEn) {
      return mRow.month_label || mRow.year_month;
    }
    if (mRow.year_month) {
      const [y, m] = mRow.year_month.split('-');
      return `${y}年${parseInt(m, 10)}月`;
    }
    return mRow.month_label;
  };

  // Navigate periods dynamically
  const handlePrev = () => {
    const [y, m] = selectedMonth.split('-').map(Number);
    if (period === 'monthly') {
      const prev = new Date(y, m - 2, 1);
      setSelectedMonth(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`);
    } else if (period === 'quarterly') {
      const prev = new Date(y, m - 4, 1);
      setSelectedMonth(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`);
    } else if (period === 'ytd') {
      setSelectedMonth(`${y - 1}-${String(m).padStart(2, '0')}`);
    } else if (period === '6m') {
      const prev = new Date(y, m - 7, 1);
      setSelectedMonth(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`);
    }
  };

  const handleNext = () => {
    const [y, m] = selectedMonth.split('-').map(Number);
    if (period === 'monthly') {
      const next = new Date(y, m, 1);
      setSelectedMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
    } else if (period === 'quarterly') {
      const next = new Date(y, m + 2, 1);
      setSelectedMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
    } else if (period === 'ytd') {
      setSelectedMonth(`${y + 1}-${String(m).padStart(2, '0')}`);
    } else if (period === '6m') {
      const next = new Date(y, m + 5, 1);
      setSelectedMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
    }
  };

  const goToday = () => {
    setSelectedMonth(getInitialMonth());
    if (period === 'custom') {
      const init = getInitialCustomDates();
      setCustomStartDate(init.start);
      setCustomEndDate(init.end);
    }
  };

  // Real data mapped from database calculations
  const incomeCategories = reportData?.activity?.income_categories || [];
  const expenseCategories = reportData?.activity?.expense_categories || [];
  const netWorthTrend = reportData?.net_worth?.trend || [];
  const investmentAccounts = reportData?.investments?.accounts || [];

  const handleExportCSV = () => {
    const header = isEn
      ? 'Category,Transaction Count,Amount,Percentage'
      : '分类,交易记录数,金额,占总计百分比';
    const csvContent =
      'data:text/csv;charset=utf-8,\uFEFF' +
      [header]
        .concat(expenseCategories.map((e) => `"${e.name}",${e.count},${e.amount},"${e.percentage}"`))
        .join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `famledger_activity_${selectedMonth}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6 pb-24 max-w-7xl mx-auto w-full max-w-full overflow-x-hidden">
      {/* ── 1. Page Header (Exact 3.png) ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            {t('analytics.title', tx("统计报表"))}
          </h1>
          <p className="text-xs text-zinc-500 mt-1">{t('analytics.subtitle', tx("您财务健康状况的全面洞察"))}</p>
        </div>

        <button
          onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs cursor-pointer"
        >
          <Printer className="w-3.5 h-3.5" />
          <span>{t('analytics.print', tx("打印报表"))}</span>
        </button>
      </div>

      {/* ── 2. Time Range Selector Pills & Month Navigator ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        {/* Period Pills */}
        <div className="w-full sm:w-auto flex sm:inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl overflow-x-auto max-w-full">
          {[
            { id: 'monthly', label: t('analytics.periods.monthly', tx("本月")) },
            { id: 'quarterly', label: t('analytics.periods.quarterly', tx("本季度")) },
            { id: 'ytd', label: t('analytics.periods.ytd', tx("今年")) },
            { id: '6m', label: t('analytics.periods.sixMonths', tx("近半年")) },
            { id: 'custom', label: t('analytics.periods.customShort', tx("自定义")), fullLabel: t('analytics.periods.custom', tx("自定义范围")) },
          ].map((item) => (
            <button
              key={item.id}
              data-testid="analytics-period"
              data-period={item.id}
              aria-pressed={period === item.id}
              onClick={() => setPeriod(item.id)}
              className={`flex-1 sm:flex-initial text-center px-1.5 sm:px-3 py-1.5 text-xs font-semibold rounded-lg transition-all whitespace-nowrap cursor-pointer ${
                period === item.id
                  ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                  : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
              }`}
            >
              <span className="sm:hidden">{tx(item.label)}</span>
              <span className="hidden sm:inline">{tx(item.fullLabel || item.label)}</span>
            </button>
          ))}
        </div>

        {/* Period / Range Navigator */}
        {period === 'custom' ? (
          <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap">
            <div className="flex items-center gap-1.5 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-2.5 py-1 text-xs shadow-2xs">
              <span className="text-zinc-400">{t('analytics.range.from', tx("从"))}</span>
              <CalendarDateInput
                label="起始日期"
                data-testid="custom-start-date"
                value={customStartDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                className="bg-transparent text-zinc-800 dark:text-zinc-200 font-mono text-xs focus:outline-hidden"
              />
              <span className="text-zinc-400">{t('analytics.range.to', tx("至"))}</span>
              <CalendarDateInput
                label="结束日期"
                data-testid="custom-end-date"
                value={customEndDate}
                onChange={(e) => setCustomEndDate(e.target.value)}
                className="bg-transparent text-zinc-800 dark:text-zinc-200 font-mono text-xs focus:outline-hidden"
              />
            </div>
            <button
              onClick={goToday}
              className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs cursor-pointer transition-colors"
            >
              {t('analytics.range.thisMonth', tx("本月"))}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <div className="flex items-center border border-zinc-200 dark:border-zinc-800 rounded-lg bg-white dark:bg-zinc-900 p-0.5">
              <button
                onClick={handlePrev}
                title={t('analytics.range.prevPeriod', tx("上一周期"))}
                data-testid="prev-period-btn"
                className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors cursor-pointer"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={handleNext}
                title={t('analytics.range.nextPeriod', tx("下一周期"))}
                data-testid="next-period-btn"
                className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors cursor-pointer"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>

            <div
              data-testid="period-display-label"
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 shadow-2xs select-none"
            >
              <span>{tx(periodDisplay)}</span>
            </div>

            <button
              onClick={goToday}
              data-testid="go-today-btn"
              className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs cursor-pointer transition-colors"
            >
              {t('analytics.range.currentPeriod', tx("本期"))}
            </button>
          </div>
        )}
      </div>

      {(loading || historyLoading) && reportData && <div role="status" className="text-xs text-zinc-500">{tx(historyLoading && !historyReady ? '正在加载历史走势…' : '正在刷新...')}</div>}
      {loading && !reportData ? (
        <div role="status" className="p-8 text-center text-sm text-zinc-500">{isEn ? tx("Loading report…") : tx("正在加载报表…")}</div>
      ) : loadError ? (
        <div role="alert" className="p-6 rounded-xl border border-rose-200 text-sm text-rose-600 space-y-3">
          <p>{tx(loadError)}</p>
          <button onClick={() => setRetryCount((value) => value + 1)} className="px-3 py-2 rounded-lg border border-current">{isEn ? tx("Retry") : tx("重试")}</button>
        </div>
      ) : <>
      {/* ── 3. 4 Major KPI Cards (Calculated from Real Database) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Income */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>{t('analytics.kpis.totalIncome', tx("总收入"))}</span>
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            {fmt(reportData?.kpis?.total_income || 0)}
          </div>
          {reportData?.kpis?.income_pct_change != null ? (
            <div className="text-[11px] text-zinc-400 flex items-center gap-1">
              <span
                className={`font-bold ${
                  reportData.kpis.income_pct_change >= 0 ? 'text-emerald-600' : 'text-rose-600'
                }`}
              >
                {reportData.kpis.income_pct_change >= 0
                  ? `↑ +${reportData.kpis.income_pct_change}%`
                  : `↓ ${reportData.kpis.income_pct_change}%`}
              </span>
              <span>{t('analytics.kpis.vsLastPeriod', tx("与上一周期相比"))}</span>
            </div>
          ) : (
            <div className="text-[11px] text-zinc-400">{t('analytics.kpis.noCompareData', tx("环比暂无对比数据"))}</div>
          )}
        </div>

        {/* Total Expense */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <TrendingDown className="w-3.5 h-3.5" />
            <span>{t('analytics.kpis.totalExpense', tx("总支出"))}</span>
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            {fmt(reportData?.kpis?.total_expense || 0)}
          </div>
          {reportData?.kpis?.expense_pct_change != null ? (
            <div className="text-[11px] text-zinc-400 flex items-center gap-1">
              <span
                className={`font-bold ${
                  reportData.kpis.expense_pct_change <= 0 ? 'text-emerald-600' : 'text-rose-600'
                }`}
              >
                {reportData.kpis.expense_pct_change <= 0
                  ? `↓ ${reportData.kpis.expense_pct_change}%`
                  : `↑ +${reportData.kpis.expense_pct_change}%`}
              </span>
              <span>{t('analytics.kpis.vsLastPeriod', tx("与上一周期相比"))}</span>
            </div>
          ) : (
            <div className="text-[11px] text-zinc-400">{t('analytics.kpis.noCompareData', tx("环比暂无对比数据"))}</div>
          )}
        </div>

        {/* Net Savings */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <Layers className="w-3.5 h-3.5" />
            <span>{t('analytics.kpis.netSavings', tx("净储蓄"))}</span>
          </div>
          <div
            className={`text-2xl font-bold font-mono ${
              (reportData?.kpis?.net_savings || 0) >= 0
                ? 'text-emerald-600 dark:text-emerald-400'
                : 'text-rose-600 dark:text-rose-400'
            }`}
          >
            {fmt(reportData?.kpis?.net_savings || 0)}
          </div>
          <div className="text-[11px] text-zinc-400">{t('analytics.kpis.incomeMinusExpense', tx("收入减净支出，计入退款汇兑损益"))}</div>
        </div>

        {/* Budget Performance */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <PieIcon className="w-3.5 h-3.5" />
            <span>{t('analytics.kpis.savingsRate', tx("储蓄率"))}</span>
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            {reportData?.kpis?.savings_rate || 0}%
          </div>
          <div className="space-y-1">
            <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-1.5 rounded-full overflow-hidden">
              <div
                className={`h-full ${
                  (reportData?.kpis?.savings_rate || 0) >= 0 ? 'bg-emerald-500' : 'bg-rose-500'
                }`}
                style={{ width: `${Math.min(100, Math.max(0, Math.abs(reportData?.kpis?.savings_rate || 0)))}%` }}
              />
            </div>
            <div className="text-[11px] text-zinc-400">{t('analytics.kpis.savingsRateDesc', tx("资金留存比率"))}</div>
          </div>
        </div>
      </div>

      {/* ── 4. Section 1: 趋势与洞察 (Trends & Insights, Real DB Calculation) ── */}
      <div data-view-section="trends" className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
        <div
          onClick={() => toggleSection('trends')}
          className="p-5 flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors border-b border-zinc-100 dark:border-zinc-800"
        >
          <div className="flex items-center gap-2">
            <ChevronDown
              className={`w-4 h-4 text-zinc-400 transition-transform ${
                sectionsOpen.trends ? '' : '-rotate-90'
              }`}
            />
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">
              {t('analytics.trends.title', tx("趋势与洞察"))}
            </h2>
          </div>
        </div>

        {sectionsOpen.trends && (historyReady ? (
          <div className="p-5 space-y-6">
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  {t('analytics.trends.monthlyBreakdown', tx("月度明细"))}
                </h3>
                <span className="sm:hidden text-[11px] text-zinc-400 font-medium flex items-center gap-1">
                  <span>{t('analytics.trends.swipeHint', tx("左右滑动查看更多 ⇄"))}</span>
                </span>
              </div>
              <div className="relative -mx-5 sm:mx-0 px-5 sm:px-0">
                <div className="overflow-x-auto scrollbar-thin pb-1">
                  <table className="w-full min-w-[580px] text-xs text-left whitespace-nowrap">
                    <thead>
                      <tr className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 font-medium">
                        <th className="py-2.5 px-3 sticky left-0 bg-white dark:bg-zinc-900 z-10 shadow-[1px_0_0_0_rgba(0,0,0,0.06)] dark:shadow-[1px_0_0_0_rgba(255,255,255,0.06)]">
                          {t('analytics.trends.month', tx("月份"))}
                        </th>
                        <th className="py-2.5 px-3 text-right">{t('analytics.trends.income', tx("收入"))}</th>
                        <th className="py-2.5 px-3 text-right">{t('analytics.trends.expense', tx("支出"))}</th>
                        <th className="py-2.5 px-3 text-right">{t('analytics.trends.net', tx("净额"))}</th>
                        <th className="py-2.5 px-3 text-right">{t('analytics.trends.savingsRate', tx("储蓄率"))}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-mono">
                      {(reportData?.trends?.monthly_breakdown || []).map((mRow) => (
                        <tr key={mRow.year_month} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20">
                          <td className="py-3 px-3 font-sans font-semibold text-zinc-800 dark:text-zinc-200 sticky left-0 bg-white dark:bg-zinc-900 z-10 shadow-[1px_0_0_0_rgba(0,0,0,0.06)] dark:shadow-[1px_0_0_0_rgba(255,255,255,0.06)]">
                            <span>{formatMonthDisplay(mRow)}</span>
                            {mRow.is_current && (
                              <span className="ml-1.5 text-[11px] font-normal px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 dark:bg-blue-950/60 dark:text-blue-400">
                                {t('analytics.trends.current', tx("当前"))}
                              </span>
                            )}
                          </td>
                          <td className="py-3 px-3 text-right text-zinc-800 dark:text-zinc-200">{fmt(mRow.income)}</td>
                          <td className="py-3 px-3 text-right text-zinc-800 dark:text-zinc-200">{fmt(mRow.expense)}</td>
                          <td
                            className={`py-3 px-3 text-right font-bold ${
                              mRow.net >= 0 ? 'text-emerald-600' : 'text-rose-600'
                            }`}
                          >
                            {fmt(mRow.net)}
                          </td>
                          <td
                            className={`py-3 px-3 text-right font-bold ${
                              mRow.net >= 0 ? 'text-emerald-600' : 'text-rose-600'
                            }`}
                          >
                            {mRow.savings_rate}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* 3 Monthly Averages Boxes */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.trends.avgIncome', tx("月均收入"))}
                </span>
                <div className="text-lg font-bold font-mono text-emerald-600 mt-1">
                  {fmt(reportData?.trends?.averages?.income || 0)}
                </div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.trends.avgExpense', tx("月均支出"))}
                </span>
                <div className="text-lg font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  {fmt(reportData?.trends?.averages?.expense || 0)}
                </div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.trends.avgSavings', tx("月均储蓄"))}
                </span>
                <div
                  className={`text-lg font-bold font-mono mt-1 ${
                    (reportData?.trends?.averages?.savings || 0) >= 0 ? 'text-emerald-600' : 'text-rose-600'
                  }`}
                >
                  {fmt(reportData?.trends?.averages?.savings || 0)}
                </div>
              </div>
            </div>
          </div>
        ) : <HistoryStatus error={historyFailure} onRetry={retry} />)}
      </div>

      {/* ── 5. Section 2: 活动明细 (Activity Breakdown with Refunds!) ── */}
      <div data-view-section="activity" className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
        <div
          onClick={() => toggleSection('activity')}
          className="p-5 flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors border-b border-zinc-100 dark:border-zinc-800"
        >
          <div className="flex items-center gap-2">
            <ChevronDown
              className={`w-4 h-4 text-zinc-400 transition-transform ${
                sectionsOpen.activity ? '' : '-rotate-90'
              }`}
            />
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">
              {t('analytics.activity.title', tx("活动明细"))}
            </h2>
          </div>

          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={handleExportCSV}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-200 transition-colors cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" />
              <span>{t('analytics.activity.csv', 'CSV')}</span>
            </button>
            <button
              onClick={() => window.open('https://docs.google.com/spreadsheets', '_blank')}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-200 transition-colors cursor-pointer"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>{t('analytics.activity.openInGoogleSheets', tx("在 Google 表格中打开"))}</span>
            </button>
          </div>
        </div>

        {sectionsOpen.activity && (
          <div className="p-5 space-y-6">
            {/* 1. Income Table */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800 dark:text-zinc-200">
                <TrendingUp className="w-3.5 h-3.5 text-emerald-600" />
                <span>{t('analytics.activity.income', tx("收入:"))}</span>
                <span className="font-mono text-emerald-600 font-bold">{fmt(reportData?.kpis?.total_income || 0)}</span>
              </div>

              <div className="border border-zinc-100 dark:border-zinc-800 rounded-xl overflow-x-auto scrollbar-thin">
                <table className="w-full min-w-[440px] text-xs whitespace-nowrap">
                  <thead>
                    <tr className="bg-zinc-50 dark:bg-zinc-800/40 text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                      <th className="py-2.5 px-4 text-left">{t('analytics.activity.category', tx("分类"))}</th>
                      <th className="py-2.5 px-4 text-right">{t('analytics.activity.amount', tx("金额"))}</th>
                      <th className="py-2.5 px-4 text-right">{t('analytics.activity.percentage', tx("占总计百分比"))}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {incomeCategories.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="py-4 text-center text-zinc-400">
                          {t('analytics.activity.noIncome', tx("本周期暂无收入入账"))}
                        </td>
                      </tr>
                    ) : (
                      incomeCategories.map((c) => (
                        <tr key={c.name} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20">
                          <td className="py-3 px-4 flex items-center gap-2">
                            <span className="w-5 h-5 rounded-md bg-amber-50 dark:bg-amber-950/40 flex items-center justify-center text-xs">
                              {c.icon || '💰'}
                            </span>
                            <span className="font-medium text-zinc-800 dark:text-zinc-200">
                              {c.name} <span className="text-zinc-400 font-normal font-mono">({c.count} {t('analytics.activity.records', tx("条记录"))})</span>
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right font-mono font-semibold text-emerald-600">
                            {fmt(c.amount)}
                          </td>
                          <td className="py-3 px-4 text-right font-mono text-zinc-500">{c.percentage}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2. Expense Table with Refund */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800 dark:text-zinc-200">
                <TrendingDown className="w-3.5 h-3.5 text-zinc-600" />
                <span>{t('analytics.activity.expense', tx("支出:"))}</span>
                <span className="font-mono font-bold text-zinc-900 dark:text-white">{fmt(reportData?.kpis?.total_expense || 0)}</span>
              </div>

              <div className="border border-zinc-100 dark:border-zinc-800 rounded-xl overflow-x-auto scrollbar-thin">
                <table className="w-full min-w-[440px] text-xs whitespace-nowrap">
                  <thead>
                    <tr className="bg-zinc-50 dark:bg-zinc-800/40 text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                      <th className="py-2.5 px-4 text-left">{t('analytics.activity.category', tx("分类"))}</th>
                      <th className="py-2.5 px-4 text-right">{t('analytics.activity.amount', tx("金额"))}</th>
                      <th className="py-2.5 px-4 text-right">{t('analytics.activity.percentage', tx("占总计百分比"))}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {expenseCategories.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="py-4 text-center text-zinc-400">
                          {t('analytics.activity.noExpense', tx("本周期暂无消费支出"))}
                        </td>
                      </tr>
                    ) : (
                      expenseCategories.map((c) => (
                        <tr key={c.name} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20">
                          <td className="py-3 px-4 flex items-center gap-2">
                            <span className="w-5 h-5 rounded-md bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-xs">
                              {c.icon || '📦'}
                            </span>
                            <span className="font-medium text-zinc-800 dark:text-zinc-200">
                              {categoryLabel(c.name)} <span className="text-zinc-400 font-normal font-mono">({c.count} {t('analytics.activity.records', tx("条记录"))})</span>
                            </span>
                          </td>
                          <td className="py-3 px-4 text-right font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                            {fmt(c.amount)}
                          </td>
                          <td className="py-3 px-4 text-right font-mono text-zinc-500">{c.percentage}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="text-[11px] text-zinc-400 px-1 pt-1">
                {t('analytics.activity.showingCount', {
                  count: reportData?.activity?.total_transactions_count || 0,
                  defaultValue: `显示 ${reportData?.activity?.total_transactions_count || 0} 条真实流水记录`,
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 6. Section 3: 净资产 (Net Worth, Real DB Calculation) ── */}
      <div data-view-section="netWorth" className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
        <div
          onClick={() => toggleSection('netWorth')}
          className="p-5 flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors border-b border-zinc-100 dark:border-zinc-800"
        >
          <div className="flex items-center gap-2">
            <ChevronDown
              className={`w-4 h-4 text-zinc-400 transition-transform ${
                sectionsOpen.netWorth ? '' : '-rotate-90'
              }`}
            />
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">
              {t('analytics.netWorth.title', tx("净资产"))}
            </h2>
          </div>
        </div>

        {sectionsOpen.netWorth && (
          <div className="p-5 space-y-6">
            {/* Top 3 Net Worth Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.netWorth.current', tx("当前净资产"))}
                </span>
                <div
                  className={`text-xl font-bold font-mono mt-1 ${
                    (reportData?.net_worth?.current || 0) >= 0 ? 'text-emerald-600' : 'text-rose-600'
                  }`}
                >
                  {fmt(reportData?.net_worth?.current || 0)}
                </div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.netWorth.currentSavings', tx("本期储蓄净结余"))}
                </span>
                <div
                  className={`text-xl font-bold font-mono mt-1 ${
                    (reportData?.kpis?.net_savings || 0) >= 0 ? 'text-emerald-600' : 'text-rose-600'
                  }`}
                >
                  {fmt(reportData?.kpis?.net_savings || 0)}
                </div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.netWorth.assetsAndLiabilities', tx("资产与负债"))}
                </span>
                <div className="text-xl font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  {fmt(reportData?.net_worth?.assets_total || 0)}{' '}
                  <span className="text-xs font-normal text-rose-500">
                    - {fmt(reportData?.net_worth?.liabilities_total || 0)}
                  </span>
                </div>
              </div>
            </div>

            {/* Rising Green Line Chart */}
            <p className="text-[11px] text-zinc-500">{tx(reportData?.net_worth?.trend_label)} {tx("；依据期初、消费、转账、退款和对账活动。个人借贷未记录完整还款历史，未纳入历史曲线。")}</p>
            <div className="h-44 w-full">
              <Suspense fallback={<div role="status" className="h-full flex items-center justify-center text-xs text-zinc-500">{tx('正在加载图表…')}</div>}>
                {historyReady ? <NetWorthChart data={netWorthTrend} currencySymbol={reportData?.currency_symbol || symbol} />
                  : <HistoryStatus error={historyFailure} onRetry={retry} />}
              </Suspense>
            </div>

            {/* Assets vs Liabilities Breakdown Table */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              {/* Assets column */}
              <div className="p-4 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50/30 dark:bg-zinc-800/20 space-y-2">
                <span className="font-bold text-zinc-700 dark:text-zinc-300 block mb-2">
                  {t('analytics.netWorth.assets', tx("资产"))}
                </span>
                <div className="flex justify-between py-1 border-b border-zinc-100 dark:border-zinc-800">
                  <span className="text-zinc-500">{t('analytics.netWorth.cash', tx("现金及其他资产"))}</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">
                    {fmt(reportData?.net_worth?.cash_total || 0)}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-zinc-500">{t('analytics.netWorth.invest', tx("投资理财"))}</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">
                    {fmt(reportData?.net_worth?.invest_total || 0)}
                  </span>
                </div>
              </div>

              {/* Liabilities column */}
              <div className="p-4 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50/30 dark:bg-zinc-800/20 space-y-2">
                <span className="font-bold text-zinc-700 dark:text-zinc-300 block mb-2">
                  {t('analytics.netWorth.liabilities', tx("负债"))}
                </span>
                <div className="flex justify-between py-1 border-b border-zinc-100 dark:border-zinc-800">
                  <span className="text-zinc-500">{t('analytics.netWorth.credit', tx("信用卡"))}</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">
                    {fmt(reportData?.net_worth?.credit_total || 0)}
                  </span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-zinc-500">{t('analytics.netWorth.loan', tx("贷款及其他负债"))}</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">
                    {fmt(reportData?.net_worth?.loan_total || 0)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 7. Section 4: 投资表现 (Investments, Real DB Calculation) ── */}
      <div data-view-section="investments" className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
        <div
          onClick={() => toggleSection('investments')}
          className="p-5 flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors border-b border-zinc-100 dark:border-zinc-800"
        >
          <div className="flex items-center gap-2">
            <ChevronDown
              className={`w-4 h-4 text-zinc-400 transition-transform ${
                sectionsOpen.investments ? '' : '-rotate-90'
              }`}
            />
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">
              {t('analytics.investments.title', tx("投资表现"))}
            </h2>
          </div>
        </div>

        {sectionsOpen.investments && (
          <div className="p-5 space-y-6">
            {/* 5 Stat Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.investments.portfolioValue', tx("投资组合价值"))}
                </span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  {fmt(reportData?.investments?.portfolio_value || 0)}
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.investments.totalReturn', tx("总回报"))}
                </span>
                <div className="text-base font-bold font-mono text-zinc-400 mt-1">-</div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.investments.periodReturn', tx("本期回报"))}
                </span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  {fmt(0)} <span className="text-xs font-normal text-zinc-400">(0.0%)</span>
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.investments.periodDeposit', tx("本期投入"))}
                </span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  {fmt(0)}
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">
                  {t('analytics.investments.periodWithdrawal', tx("本期提取"))}
                </span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  {fmt(0)}
                </div>
              </div>
            </div>

            {/* Investment Accounts Grid */}
            <div className="space-y-3">
              <h3 className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                {t('analytics.investments.accountsTitle', tx("投资账户"))}
              </h3>
              {investmentAccounts.length === 0 ? (
                <div className="py-8 text-center text-xs text-zinc-400 bg-zinc-50/50 dark:bg-zinc-800/20 rounded-xl border border-zinc-100 dark:border-zinc-800">
                  {t('analytics.investments.noAccounts', tx("当前尚未录入证券/基金等投资类账户"))}
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                  {investmentAccounts.map((acc, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-xl border border-zinc-200/70 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors flex items-center justify-between shadow-2xs"
                    >
                      <div className="flex items-center gap-2.5 min-w-0 pr-2">
                        <div className="w-7 h-7 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 font-bold text-xs flex items-center justify-center shrink-0">
                          {acc.icon}
                        </div>
                        <div className="min-w-0">
                          <div className="font-semibold text-xs text-zinc-900 dark:text-white truncate">
                            {acc.name}
                          </div>
                          <div className="text-[11px] text-zinc-400">{acc.type}</div>
                        </div>
                      </div>

                      <div className="font-mono font-bold text-xs text-zinc-900 dark:text-white shrink-0">
                        {fmt(acc.balance)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
      </>}
    </div>
  );
}
