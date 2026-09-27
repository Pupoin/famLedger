import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Plus,
  ChevronDown,
  ChevronRight,
  Maximize2,
  SlidersHorizontal,
  Eye,
  EyeOff,
  BookOpen,
  LayoutGrid,
} from 'lucide-react';
import { useCurrency } from '../CurrencyContext';
import { fetchWithAuth } from '../api/fetchWithAuth';
import SureCashflowSankey from '../components/ds/SureCashflowSankey';
import SureOutflowsDonut from '../components/ds/SureOutflowsDonut';
import SureMerchantSpending from '../components/ds/SureMerchantSpending';
import SureSpendingCalendar from '../components/ds/SureSpendingCalendar';

export default function Landing() {
  const { privacyMode, togglePrivacyMode } = useCurrency();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  // Period filter: MTD | 30D | YTD | ALL
  const [period, setPeriod] = useState('MTD');
  const [periodDropdownOpen, setPeriodDropdownOpen] = useState(false);

  // Account filter
  const [accountFilter, setAccountFilter] = useState('全部');
  const [accountDropdownOpen, setAccountDropdownOpen] = useState(false);

  // Section collapse states (matching 1.png: balance_sheet, net_worth, money_in_out are collapsed by default)
  const [collapsedSections, setCollapsedSections] = useState({
    cashflow: false,
    outflows: false,
    balance_sheet: true,
    net_worth: true,
    merchant_spending: false,
    money_in_out: true,
    calendar: false,
    investment: false,
  });

  const toggleSection = (sectionKey) => {
    setCollapsedSections((prev) => ({
      ...prev,
      [sectionKey]: !prev[sectionKey],
    }));
  };

  useEffect(() => {
    async function loadDashboardData() {
      try {
        setLoading(true);
        const res = await fetchWithAuth(`/api/v1/dashboard/summary?period=${period}`);
        if (res.ok) {
          const json = await res.json();
          setData(json);
        }
      } catch (err) {
        console.error('Failed to load dashboard summary', err);
      } finally {
        setLoading(false);
      }
    }
    loadDashboardData();
  }, [period]);

  const userName = data?.user_name || 'sliver';
  const currencySymbol = '¥';

  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <div className="w-7 h-7 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin dark:border-zinc-100" />
        <span className="text-xs text-zinc-400 font-medium">正在载入财务概览...</span>
      </div>
    );
  }

  return (
    <div className="space-y-5 pb-12 max-w-7xl mx-auto">
      {/* ── 1. Top Breadcrumb & Controls (Exact Sure Breadcrumb) ── */}
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <div className="flex items-center gap-2">
          <BookOpen className="w-3.5 h-3.5 text-zinc-400" />
          <span>主页</span>
          <ChevronRight className="w-3 h-3 text-zinc-300" />
          <span className="text-zinc-900 dark:text-zinc-100 font-medium">仪表盘</span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            className="p-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition-colors"
            title="定制组件大小"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={togglePrivacyMode}
            className={`p-1 rounded-lg transition-colors ${
              privacyMode
                ? 'text-emerald-600 bg-emerald-500/10'
                : 'hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
            }`}
            title={privacyMode ? '显示金额' : '隐藏敏感数据'}
          >
            {privacyMode ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* ── 2. Page Welcome & Action Header ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            {`欢迎回来，${userName}`}
          </h1>
          <p className="text-xs sm:text-sm text-zinc-500 mt-1">
            以下是您的财务状况概览
          </p>
        </div>

        <div>
          <Link
            to="/add"
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-200 text-white shadow-2xs transition-all active:scale-95"
          >
            <Plus className="w-4 h-4" />
            <span>新建</span>
          </Link>
        </div>
      </div>

      {/* ── 3. Filters Row: 全部 ˇ | MTD ˇ ── */}
      <div className="flex items-center justify-end gap-2 relative">
        {/* Account Selector */}
        <div className="relative">
          <button
            type="button"
            onClick={() => {
              setAccountDropdownOpen(!accountDropdownOpen);
              setPeriodDropdownOpen(false);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-800 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors"
          >
            <span>{accountFilter}</span>
            <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
          </button>

          {accountDropdownOpen && (
            <div className="absolute right-0 top-full mt-1.5 z-30 w-36 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-lg py-1">
              {['全部', '招商银行', '中国银行', '贷款'].map((acc) => (
                <button
                  key={acc}
                  type="button"
                  onClick={() => {
                    setAccountFilter(acc);
                    setAccountDropdownOpen(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs ${
                    accountFilter === acc
                      ? 'bg-zinc-100 dark:bg-zinc-700 text-zinc-900 dark:text-white font-medium'
                      : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                  }`}
                >
                  {acc}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Period Selector (MTD, 30D, YTD, ALL) */}
        <div className="relative">
          <button
            type="button"
            onClick={() => {
              setPeriodDropdownOpen(!periodDropdownOpen);
              setAccountDropdownOpen(false);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-800 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors"
          >
            <span>{period}</span>
            <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
          </button>

          {periodDropdownOpen && (
            <div className="absolute right-0 top-full mt-1.5 z-30 w-28 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-lg py-1">
              {[
                { label: 'MTD (本月)', value: 'MTD' },
                { label: '30D (30天)', value: '30D' },
                { label: 'YTD (本年)', value: 'YTD' },
                { label: '全部', value: 'ALL' },
              ].map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => {
                    setPeriod(p.value);
                    setPeriodDropdownOpen(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 text-xs ${
                    period === p.value
                      ? 'bg-zinc-100 dark:bg-zinc-700 text-zinc-900 dark:text-white font-medium'
                      : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── 4. Main Dashboard Widgets Stream (Exact Sure Order) ── */}
      <div className="space-y-4">
        {/* ── Section 1: 现金流 (Cash Flow Sankey) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-4 pb-2">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                现金流
              </h2>
            </button>

            <button
              type="button"
              className="p-1 rounded-md text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              title="最大化查看"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.cashflow && (
            <div className="p-4 pt-0">
              <SureCashflowSankey
                data={data?.cashflow}
                currencySymbol={currencySymbol}
                height={340}
              />
            </div>
          )}
        </div>

        {/* ── Section 2: 支出 (Outflows Donut & Ranking) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                支出
              </h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.outflows && (
            <div className="p-4 pt-0">
              <SureOutflowsDonut
                data={data?.outflows}
                currencySymbol={currencySymbol}
              />
            </div>
          )}
        </div>

        {/* ── Section 3: 资产负债表 (Balance Sheet) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                资产负债表
              </h2>
            </button>

            <div className="inline-flex p-0.5 bg-zinc-100 dark:bg-zinc-800 rounded-lg text-xs font-medium">
              <button
                type="button"
                className="px-2.5 py-1 rounded-md bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white font-medium shadow-2xs"
              >
                按账户类型
              </button>
              <button
                type="button"
                className="px-2.5 py-1 rounded-md text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200"
              >
                按金融机构
              </button>
            </div>
          </div>

          {!collapsedSections.balance_sheet && (
            <div className="p-4 pt-0 text-sm text-zinc-500">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
                  <span className="text-xs text-zinc-400">总资产</span>
                  <p className="text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                    ¥{data?.balance_sheet?.total_assets?.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                  </p>
                </div>
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
                  <span className="text-xs text-zinc-400">总负债</span>
                  <p className="text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                    ¥{data?.balance_sheet?.total_liabilities?.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                  </p>
                </div>
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/50 rounded-xl">
                  <span className="text-xs text-zinc-400">净资产</span>
                  <p className="text-lg font-bold font-mono text-red-600 mt-1">
                    ¥{data?.balance_sheet?.net_worth?.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Section 4: 净资产 (Net Worth) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                净资产
              </h2>
            </button>
          </div>

          {!collapsedSections.net_worth && (
            <div className="p-4 pt-0">
              <span className="text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-100">
                -¥81,382.10
              </span>
              <p className="text-xs text-zinc-400 mt-1">过去 30 天无明显变动</p>
            </div>
          )}
        </div>

        {/* ── Section 5: 按商户统计的支出分布 (Merchant Spending) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                按商户统计的支出分布
              </h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.merchant_spending && (
            <div className="p-4 pt-0">
              <SureMerchantSpending
                data={data?.merchants}
                currencySymbol={currencySymbol}
              />
            </div>
          )}
        </div>

        {/* ── Section 6: Money In / Out ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                Money In / Out
              </h2>
            </button>
          </div>

          {!collapsedSections.money_in_out && (
            <div className="p-4 pt-0 text-sm text-zinc-500">
              <div className="flex items-center gap-6">
                <div>
                  <span className="text-xs text-zinc-400 block">Money In</span>
                  <span className="text-lg font-bold font-mono text-emerald-600 block mt-1">+¥548.03</span>
                </div>
                <div>
                  <span className="text-xs text-zinc-400 block">Money Out</span>
                  <span className="text-lg font-bold font-mono text-red-600 block mt-1">-¥2,814.60</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Section 7: 消费日历热力图 (Spending Calendar) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                消费日历热力图
              </h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.calendar && (
            <div className="p-4 pt-0">
              <SureSpendingCalendar
                data={data?.spending_calendar}
                currencySymbol={currencySymbol}
              />
            </div>
          )}
        </div>

        {/* ── Section 8: 投资 (Investment) ── */}
        <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xs overflow-hidden">
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
              <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-100">
                投资
              </h2>
            </button>
          </div>

          {/* Body */}
          {!collapsedSections.investment && (
            <div className="p-4 pt-2">
              <span className="text-xs text-zinc-400 font-medium block">
                投资
              </span>
              <span className="text-3xl sm:text-4xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-1 block">
                ¥509,058.74
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
