import { chartMoney } from '../utils/chartMoney';
import { dateLabel, tx, useLocale, currentLocale } from "../localization.js";
import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Plus, ChevronLeft, ChevronDown, ChevronRight, Maximize2, SlidersHorizontal, Eye, EyeOff, BookOpen } from 'lucide-react';
import { useCurrency } from '../CurrencyContext';
import { useAuth } from '../auth/AuthContext';
import { fetchWithAuth } from '../api/fetchWithAuth';
import SureCashflowSankey from '../components/ds/SureCashflowSankey';
import SureOutflowsDonut from '../components/ds/SureOutflowsDonut';
import SureMerchantSpending from '../components/ds/SureMerchantSpending';
import SureSpendingCalendar from '../components/ds/SureSpendingCalendar';
import SureMoneyInOut from '../components/ds/SureMoneyInOut';
import FamilyInvitationPromptModal from '../components/FamilyInvitationPromptModal';
import CalendarDateInput from '../components/CalendarDateInput';
import { usePageViewState, usePageScrollRestoration } from '../PageViewContext';

export default function Landing() {
  useLocale();
  const { user } = useAuth();
  const { privacyMode, togglePrivacyMode, currency, symbol } = useCurrency();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [retryCount, setRetryCount] = useState(0);

  // Period Preset: 'monthly' | 'quarterly' | 'ytd' | '6m' | 'custom'
  const [period, setPeriod] = usePageViewState('period', 'monthly');

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

  // User filter (Exact user requirement 3: 家庭组各个用户或全部用户)
  const [userFilter, setUserFilter] = usePageViewState('userFilter', '全部');
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);

  // Section collapse states (matching 10.jpg and 11.jpg flow)
  const [collapsedSections, setCollapsedSections] = usePageViewState('collapsedSections', {
    cashflow: false,
    outflows: false,
    money_in_out: false,
    calendar: false,
    investment: false,
    merchant_spending: false,
    balance_sheet: false,
    net_worth: false,
  });

  const [balanceSheetMode, setBalanceSheetMode] = usePageViewState('balanceSheetMode', 'type'); // 'type' | 'institution'
  const [expandedGroups, setExpandedGroups] = usePageViewState('expandedGroups', {});
  usePageScrollRestoration(!loading && !!data);

  const toggleGroup = (key) => {
    setExpandedGroups((prev) => ({
      ...prev,
      [key]: prev[key] === undefined ? false : !prev[key],
    }));
  };

  const toggleSection = (sectionKey) => {
    setCollapsedSections((prev) => ({
      ...prev,
      [sectionKey]: !prev[sectionKey],
    }));
  };

  // Format dynamic period title based on selected period
  const periodDisplay = useMemo(() => {
    const [y, m] = selectedMonth.split('-').map(Number);
    if (period === 'monthly') {
      return `${y}年${String(m).padStart(2, '0')}月`;
    }
    if (period === 'quarterly') {
      const q = Math.floor((m - 1) / 3) + 1;
      const startM = (q - 1) * 3 + 1;
      const endM = startM + 2;
      return `${y}年 Q${q} (${String(startM).padStart(2, '0')}月-${String(endM).padStart(2, '0')}月)`;
    }
    if (period === 'ytd') {
      return `${y} 今年 (01月-${String(m).padStart(2, '0')}月)`;
    }
    if (period === '6m') {
      const endD = new Date(y, m - 1, 1);
      const startD = new Date(y, m - 6, 1);
      const sY = startD.getFullYear();
      const sM = String(startD.getMonth() + 1).padStart(2, '0');
      const eY = endD.getFullYear();
      const eM = String(endD.getMonth() + 1).padStart(2, '0');
      return `近半年 (${sY}/${sM} - ${eY}/${eM})`;
    }
    if (period === 'custom') {
      return `${customStartDate} 至 ${customEndDate}`;
    }
    return `${y}年${m}月`;
  }, [period, selectedMonth, customStartDate, customEndDate]);

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

  useEffect(() => {
    let activeController;
    async function loadDashboardData() {
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      try {
        setLoading(true);
        setLoadError('');
        setData(null);
        const queryParams = new URLSearchParams();
        queryParams.set('period', period);
        if (period === 'custom') {
          if (customStartDate) queryParams.set('start_date', customStartDate);
          if (customEndDate) queryParams.set('end_date', customEndDate);
        } else {
          queryParams.set('selected_month', selectedMonth);
        }
        if (userFilter && userFilter !== '全部') {
          queryParams.set('user', userFilter);
        }
        const res = await fetchWithAuth(`/api/v1/dashboard/summary?${queryParams.toString()}`, { signal: controller.signal });
        if (!res.ok) {
          const failure = await res.json().catch(() => ({}));
          throw new Error(typeof failure.detail === 'string' ? failure.detail : '无法加载财务概览');
        }
        const json = await res.json();
        if (!controller.signal.aborted) setData(json);
      } catch (err) {
        if (!controller.signal.aborted) setLoadError(tx(err.message || '无法加载财务概览'));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    loadDashboardData();

    window.addEventListener('transaction-added', loadDashboardData);
    window.addEventListener('transaction-updated', loadDashboardData);
    window.addEventListener('transaction-deleted', loadDashboardData);
    window.addEventListener('accounts-updated', loadDashboardData);
    window.addEventListener('preferences-updated', loadDashboardData);

    return () => {
      activeController?.abort();
      window.removeEventListener('transaction-added', loadDashboardData);
      window.removeEventListener('transaction-updated', loadDashboardData);
      window.removeEventListener('transaction-deleted', loadDashboardData);
      window.removeEventListener('accounts-updated', loadDashboardData);
      window.removeEventListener('preferences-updated', loadDashboardData);
    };
  }, [period, selectedMonth, customStartDate, customEndDate, userFilter, currency, retryCount]);

  const userName = data?.user_name || user?.displayName || user?.username || '用户';
  const currencySymbol = data?.currency_symbol || symbol;
  const formatAmount = value => chartMoney(value, currencySymbol, privacyMode, currentLocale());

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <div className="w-7 h-7 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin dark:border-zinc-100" />
        <span className="text-xs text-zinc-400 font-medium">{tx("正在载入财务概览...")}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 lg:gap-4 pb-12 max-w-7xl mx-auto w-full max-w-full overflow-x-hidden">
      {!privacyMode && (data?.fx_gain || data?.fx_loss) ? <div className="text-sm text-zinc-500">{tx("汇兑收益")} {currencySymbol}{data.fx_gain || 0} {tx("· 汇兑损失")} {currencySymbol}{data.fx_loss || 0} {tx("（已包含在实际退款到账中）")}</div> : null}
      {/* 首次收到家庭组邀请提示弹窗（二次免扰） */}
      <FamilyInvitationPromptModal />

      {/* ── 1. Top Breadcrumb & Controls (Exact Sure Breadcrumb, hidden on mobile per 10.jpg) ── */}
      <div className="hidden lg:flex items-center justify-between text-xs text-zinc-500">
        <div className="flex items-center gap-2">
          <BookOpen className="w-3.5 h-3.5 text-zinc-400" />
          <span>{tx("主页")}</span>
          <ChevronRight className="w-3 h-3 text-zinc-300" />
          <span className="text-zinc-900 dark:text-zinc-100 font-medium">{tx("仪表盘")}</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            className="p-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors"
            title={tx("定制组件大小")}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            data-testid="privacy-toggle"
            onClick={togglePrivacyMode}
            className={`p-1 rounded-lg transition-colors ${
              privacyMode
                ? 'text-emerald-600 bg-emerald-500/10'
                : 'hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
            }`}
            title={privacyMode ? tx("显示金额") : tx("隐藏敏感数据")}
          >
            {privacyMode ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* ── 2. Page Welcome & Action Header (Desktop Only, hidden on mobile per 10.jpg) ── */}
      <div className="hidden lg:flex items-start justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            {tx("欢迎回来，{p0}", {p0: (userName)})}
          </h1>
          <p className="text-xs sm:text-sm text-zinc-500 mt-1">{tx("以下是您的财务状况概览")}</p>
        </div>

        <div>
          <Link
            to="/add"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 text-white shadow-2xs transition-all active:scale-95"
          >
            <Plus className="w-4 h-4" />
            <span>{tx("新建")}</span>
          </Link>
        </div>
      </div>

      {/* ── 3. Filters Row: Period Pills + Navigator + User Selector ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {/* Left: Period Pills */}
        <div className="w-full sm:w-auto flex sm:inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl overflow-x-auto max-w-full">
          {[
            { id: 'monthly', label: '本月' },
            { id: 'quarterly', label: '本季度' },
            { id: 'ytd', label: '今年' },
            { id: '6m', label: '近半年' },
            { id: 'custom', label: '自定义', fullLabel: '自定义范围' },
          ].map((item) => (
            <button
              key={item.id}
              data-testid="dashboard-period"
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

        {/* Right: Dynamic Navigator + User Selector */}
        <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap justify-between sm:justify-end">
          {period === 'custom' ? (
            <div className="flex items-center gap-1.5 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-2.5 py-1 text-xs shadow-2xs">
              <span className="text-zinc-400">{tx("从")}</span>
              <CalendarDateInput
                label="起始日期"
                data-testid="custom-start-date"
                value={customStartDate}
                onChange={(e) => setCustomStartDate(e.target.value)}
                className="bg-transparent text-zinc-800 dark:text-zinc-200 font-mono text-xs focus:outline-hidden"
              />
              <span className="text-zinc-400">{tx("至")}</span>
              <CalendarDateInput
                label="结束日期"
                data-testid="custom-end-date"
                value={customEndDate}
                onChange={(e) => setCustomEndDate(e.target.value)}
                className="bg-transparent text-zinc-800 dark:text-zinc-200 font-mono text-xs focus:outline-hidden"
              />
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex items-center border border-zinc-200 dark:border-zinc-800 rounded-lg bg-white dark:bg-zinc-900 p-0.5">
                <button
                  onClick={handlePrev}
                  title={tx("上一周期")}
                  data-testid="prev-period-btn"
                  className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors cursor-pointer"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  onClick={handleNext}
                  title={tx("下一周期")}
                  data-testid="next-period-btn"
                  className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors cursor-pointer"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>

              <div
                data-testid="period-display-label"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 shadow-2xs select-none whitespace-nowrap"
              >
                <span>{dateLabel(periodDisplay)}</span>
              </div>
            </div>
          )}

          <button
            onClick={goToday}
            data-testid="go-today-btn"
            className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs cursor-pointer transition-colors whitespace-nowrap"
          >{tx("本期")}</button>

          {/* User Selector Dropdown */}
          <div className="relative">
            <button
              type="button"
              data-testid="dashboard-user-filter"
              onClick={() => setUserDropdownOpen(!userDropdownOpen)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-800 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors cursor-pointer whitespace-nowrap"
            >
              <span>{userFilter === '全部' ? tx("全部用户") : userFilter}</span>
              <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
            </button>

            {userDropdownOpen && (
              <div className="absolute right-0 top-full mt-1.5 z-30 w-40 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-lg py-1">
                <div className="px-3 py-1 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">{tx("家庭成员筛选")}</div>
                <button
                  type="button"
                  onClick={() => {
                    setUserFilter('全部');
                    setUserDropdownOpen(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs cursor-pointer ${
                    userFilter === '全部'
                      ? 'bg-zinc-100 dark:bg-zinc-700 text-zinc-900 dark:text-white font-medium'
                      : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                  }`}
                >{tx("全部用户")}</button>
                {(data?.family_members && data.family_members.length > 0
                  ? data.family_members
                  : [
                      { username: 'qq', display_name: '我的 (qq)', is_current: true },
                      { username: 'alice', display_name: 'alice', is_current: false },
                    ]
                ).map((m) => {
                  const label = m.is_current
                    ? tx("我的 ({p0})", {p0: (m.username)})
                    : (m.display_name && m.display_name !== m.username
                        ? `${m.display_name} (${m.username})`
                        : m.username);
                  const isSelected = userFilter === m.username || userFilter === m.display_name;
                  return (
                    <button
                      key={m.id || m.username}
                      type="button"
                      onClick={() => {
                        setUserFilter(m.username);
                        setUserDropdownOpen(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 text-xs cursor-pointer ${
                        isSelected
                          ? 'bg-zinc-100 dark:bg-zinc-700 text-zinc-900 dark:text-white font-medium'
                          : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                      }`}
                    >
                      {tx(label)}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {loadError && <div role="alert" className="p-4 rounded-xl border border-rose-200 text-sm text-rose-600 space-y-2"><p>{tx(loadError)}</p><button onClick={() => setRetryCount((value) => value + 1)} className="px-3 py-2 rounded-lg border border-current">{tx("重试")}</button></div>}
      {!loadError && <>
      {/* ── 4. Main Dashboard Widgets Stream (Exact Sure Order) ── */}
      <div className="space-y-4">
        {/* ── Section 1: 现金流 (Cash Flow Sankey) ── */}
        <div data-view-section="cashflow" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-3.5 pt-3 pb-1.5 sm:p-4 sm:pb-2">
            <button
              type="button"
              onClick={() => toggleSection('cashflow')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.cashflow ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("现金流")}</h2>
            </button>

            <button
              type="button"
              className="p-1 rounded-md text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              title={tx("最大化查看")}
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.cashflow && (
            <div className="px-2 pt-0 pb-1.5 sm:p-4 sm:pt-0">
              <SureCashflowSankey
                data={data?.cashflow}
                currencySymbol={currencySymbol}
                height={340}
                userFilter={userFilter}
                startDate={data?.period_dates?.start}
                endDate={data?.period_dates?.end}
              />
            </div>
          )}
        </div>

        {/* ── Section 2: 支出 (Outflows Donut & Ranking) ── */}
        <div data-view-section="outflows" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-4 pb-2">
            <button
              type="button"
              onClick={() => toggleSection('outflows')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.outflows ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("支出")}</h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.outflows && (
            <div className="p-4 pt-0">
              <SureOutflowsDonut
                data={data?.outflows}
                currencySymbol={currencySymbol}
                userFilter={userFilter}
                startDate={data?.period_dates?.start}
                endDate={data?.period_dates?.end}
              />
            </div>
          )}
        </div>

        {/* ── Section 3: Money In / Out (Matching 11.jpg) ── */}
        <div data-view-section="money_in_out" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          <div className="flex items-center justify-between p-4">
            <button
              type="button"
              onClick={() => toggleSection('money_in_out')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.money_in_out ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("Money In / Out")}</h2>
            </button>
          </div>

          {!collapsedSections.money_in_out && (
            <div className="p-4 pt-0">
              <SureMoneyInOut
                data={data?.money_in_out}
                currencySymbol={currencySymbol}
                userFilter={userFilter}
              />
            </div>
          )}
        </div>

        {/* ── Section 4: 消费日历热力图 (Spending Calendar, Matching 11.jpg) ── */}
        <div data-view-section="calendar" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-4 pb-2">
            <button
              type="button"
              onClick={() => toggleSection('calendar')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.calendar ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("消费日历热力图")}</h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.calendar && (
            <div className="p-4 pt-0">
              <SureSpendingCalendar
                data={data?.spending_calendar}
                currencySymbol={currencySymbol}
                reportCurrency={data?.currency || currency}
                userFilter={userFilter}
              />
            </div>
          )}
        </div>

        {/* ── Section 5: 投资 (Investment, Matching 11.jpg) ── */}
        <div data-view-section="investment" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-4 pb-2">
            <button
              type="button"
              onClick={() => toggleSection('investment')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.investment ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("投资")}</h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.investment && (
            <div className="p-4 pt-2">
              <span className="text-xs text-zinc-400 font-medium block">{tx("投资")}</span>
              <span className="text-3xl sm:text-4xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-1 block">
                {formatAmount(data?.investment?.total)}
              </span>
            </div>
          )}
        </div>

        {/* ── Section 6: 按商户统计的支出分布 (Merchant Spending) ── */}
        <div data-view-section="merchant_spending" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-4 pb-2">
            <button
              type="button"
              onClick={() => toggleSection('merchant_spending')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.merchant_spending ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("按商户统计的支出分布")}</h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.merchant_spending && (
            <div className="p-4 pt-0">
              <SureMerchantSpending
                data={data?.merchants}
                currencySymbol={currencySymbol}
                userFilter={userFilter}
                startDate={data?.period_dates?.start}
                endDate={data?.period_dates?.end}
              />
            </div>
          )}
        </div>

        {/* ── Section 7: 资产负债表 (Balance Sheet) ── */}
        <div data-view-section="balance_sheet" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          <div className="flex items-center justify-between p-4">
            <button
              type="button"
              onClick={() => toggleSection('balance_sheet')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.balance_sheet ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("资产负债表")}</h2>
            </button>

            <div className="inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl text-xs font-medium">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setBalanceSheetMode('type');
                }}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                  balanceSheetMode === 'type'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >{tx("按账户类型")}</button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setBalanceSheetMode('institution');
                }}
                className={`px-3 py-1.5 rounded-lg font-semibold transition-all ${
                  balanceSheetMode === 'institution'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
                }`}
              >{tx("按金融机构")}</button>
            </div>
          </div>

          {!collapsedSections.balance_sheet && (
            <div className="p-4 pt-0 text-sm text-zinc-500 space-y-6">
              {/* Summary Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
                  <span className="text-xs text-zinc-400">{tx("总资产")}</span>
                  <p className="text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                    {formatAmount(data?.balance_sheet?.total_assets)}
                  </p>
                </div>
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
                  <span className="text-xs text-zinc-400">{tx("总负债")}</span>
                  <p className="text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                    {formatAmount(data?.balance_sheet?.total_liabilities)}
                  </p>
                </div>
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
                  <span className="text-xs text-zinc-400">{tx("净资产")}</span>
                  <p className="text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                    {formatAmount(data?.balance_sheet?.net_worth)}
                  </p>
                </div>
              </div>

              {/* Grouped Lists (by_type or by_institution) */}
              {(() => {
                const currentSheet =
                  balanceSheetMode === 'type'
                    ? data?.balance_sheet?.by_type
                    : data?.balance_sheet?.by_institution;

                if (!currentSheet) return null;

                return ["assets", "liabilities"].map((classKey) => {
                  const classData = currentSheet?.[classKey];
                  if (!classData) return null;
                  const groups = classData.groups || [];

                  return (
                    <div key={classKey} className="space-y-3">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 inline-flex items-center gap-1.5">
                          <span>{tx(classData.name)}</span>
                          <span className="text-zinc-400">&middot;</span>
                          <span className="text-zinc-500 font-mono text-xs">
                            {formatAmount(classData.total)}
                          </span>
                        </h3>
                      </div>

                      {groups.length > 0 && (
                        <div className="space-y-3">
                          {/* Multi-segment Weight bar */}
                          <div className="h-1.5 w-full flex rounded-full overflow-hidden bg-zinc-100 dark:bg-zinc-800 gap-0.5">
                            {groups.map((group) => (
                              <div
                                key={balanceSheetMode === 'type' ? tx(group.name) : group.name}
                                className="h-full transition-all"
                                style={{
                                  width: `${Math.max(group.weight, 2)}%`,
                                  backgroundColor: group.color,
                                }}
                              />
                            ))}
                          </div>

                          {/* Color badges legend */}
                          <div className="flex flex-wrap gap-3">
                            {groups.map((group) => (
                              <div key={balanceSheetMode === 'type' ? tx(group.name) : group.name} className="flex items-center gap-1.5 text-xs">
                                <div
                                  className="h-2 w-2 rounded-full shrink-0"
                                  style={{ backgroundColor: group.color }}
                                />
                                <span className="text-zinc-500">{balanceSheetMode === 'type' ? tx(group.name) : group.name}</span>
                                <span className="font-mono text-zinc-800 dark:text-zinc-200">
                                  {Math.round(group.weight)}%
                                </span>
                              </div>
                            ))}
                          </div>

                          {/* Table Container */}
                          <div className="border border-zinc-200/90 dark:border-zinc-800 rounded-xl overflow-x-auto bg-zinc-50/50 dark:bg-zinc-800/20">
                            {/* Table Header */}
                            <div className="min-w-[320px] px-3 sm:px-4 py-2 flex items-center justify-between text-xs font-medium text-zinc-400 uppercase border-b border-zinc-200/60 dark:border-zinc-800/60">
                              <span className="flex-1 min-w-[110px]">{tx("名称")}</span>
                              <div className="flex items-center gap-2 sm:gap-4 text-right shrink-0">
                                <span className="w-12 sm:w-16">{tx("占比")}</span>
                                <span className="min-w-[85px] sm:w-24 text-right">{tx("金额")}</span>
                              </div>
                            </div>

                            {/* Groups */}
                            <div className="min-w-[320px] divide-y divide-zinc-200/60 dark:divide-zinc-800/60 bg-white dark:bg-zinc-900">
                              {groups.map((group) => {
                                const groupKey = `${classKey}-${balanceSheetMode === 'type' ? tx(group.name) : group.name}`;
                                const isExpanded = expandedGroups[groupKey] !== false; // default expanded

                                return (
                                  <div key={balanceSheetMode === 'type' ? tx(group.name) : group.name} className="overflow-hidden">
                                    <button
                                      type="button"
                                      onClick={() => toggleGroup(groupKey)}
                                      className="w-full px-3 sm:px-4 py-2.5 sm:py-3 flex items-center justify-between hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 transition-colors text-left"
                                    >
                                      <div className="flex-1 min-w-[110px] flex items-center gap-1.5 sm:gap-2 pr-2">
                                        <ChevronRight
                                          className={`w-3.5 h-3.5 text-zinc-400 transition-transform shrink-0 ${
                                            isExpanded ? 'rotate-90' : ''
                                          }`}
                                        />
                                        <span className="text-xs sm:text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
                                          {balanceSheetMode === 'type' ? tx(group.name) : group.name}
                                        </span>
                                      </div>
                                      <div className="flex items-center gap-2 sm:gap-4 text-right text-xs sm:text-sm shrink-0">
                                        <div className="w-12 sm:w-16 flex items-center justify-end gap-1">
                                          <div className="w-5 sm:w-8 h-1 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden shrink-0">
                                            <div
                                              className="h-full"
                                              style={{
                                                width: `${group.weight}%`,
                                                backgroundColor: group.color,
                                              }}
                                            />
                                          </div>
                                          <span className="text-[11px] sm:text-xs font-mono text-zinc-400">
                                            {Math.round(group.weight)}%
                                          </span>
                                        </div>
                                        <span className="min-w-[85px] sm:w-24 font-mono font-medium text-zinc-900 dark:text-zinc-100 text-right">
                                          {formatAmount(group.total)}
                                        </span>
                                      </div>
                                    </button>

                                    {/* Sub accounts list */}
                                    {isExpanded && group.accounts && group.accounts.length > 0 && (
                                      <div className="divide-y divide-zinc-100 dark:divide-zinc-800/50 bg-zinc-50/30 dark:bg-zinc-900/50">
                                        {group.accounts.map((acc) => (
                                          <div
                                            key={acc.id}
                                            className="pl-7 sm:pl-9 pr-3 sm:pr-4 py-2 sm:py-2.5 flex items-center justify-between text-xs hover:bg-zinc-100/50 dark:hover:bg-zinc-800/30 transition-colors"
                                          >
                                            <div className="flex-1 min-w-[110px] flex items-center gap-1.5 pr-2 truncate">
                                              <span className="text-zinc-900 dark:text-zinc-200 font-medium truncate">
                                                {acc.name}
                                              </span>
                                              {acc.owner && (
                                                <span className="px-1.5 py-0.5 rounded text-[11px] bg-zinc-100 dark:bg-zinc-800 text-zinc-500 shrink-0">
                                                  {acc.owner}
                                                </span>
                                              )}
                                            </div>
                                            <div className="flex items-center gap-2 sm:gap-4 text-right shrink-0">
                                              <div className="w-12 sm:w-16 flex items-center justify-end gap-1">
                                                <span className="font-mono text-zinc-400 text-[11px] sm:text-xs">
                                                  {Math.round(acc.weight)}%
                                                </span>
                                              </div>
                                              <span className="min-w-[85px] sm:w-24 font-mono text-zinc-800 dark:text-zinc-200 text-right">
                                                {formatAmount(acc.balance)}
                                              </span>
                                            </div>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          )}
        </div>

        {/* ── Section 8: 净资产 (Net Worth) ── */}
        <div data-view-section="net_worth" className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          <div className="flex items-center justify-between p-4">
            <button
              type="button"
              onClick={() => toggleSection('net_worth')}
              className="flex items-center gap-2 hover:opacity-80 transition-opacity"
            >
              {collapsedSections.net_worth ? (
                <ChevronRight className="w-4 h-4 text-zinc-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-zinc-400" />
              )}
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">{tx("净资产")}</h2>
            </button>
          </div>

          {!collapsedSections.net_worth && (
            <div className="p-4 pt-0">
              <span className={`text-2xl font-bold font-mono ${
                (data?.balance_sheet?.net_worth || 0) >= 0 ? 'text-zinc-900 dark:text-zinc-100' : 'text-rose-600'
              }`}>
                {formatAmount(data?.balance_sheet?.net_worth)}
              </span>
              <p className="text-xs text-zinc-400 mt-1">{tx("数据依据真实资产与负债账户实时计算")}</p>
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  );
}
