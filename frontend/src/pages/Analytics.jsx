import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Printer,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Download,
  ExternalLink,
  TrendingUp,
  TrendingDown,
  PieChart as PieIcon,
  Layers,
  Building,
  RotateCcw,
} from 'lucide-react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
} from 'recharts';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';
import { useTheme } from '../ThemeContext';

export default function Analytics() {
  const { t } = useTranslation();
  const { fmt } = useCurrency();
  const { theme } = useTheme();

  // Period Preset
  const [period, setPeriod] = useState('monthly'); // 'monthly' | 'quarterly' | 'ytd' | '6m' | 'custom'
  const [selectedMonth, setSelectedMonth] = useState('2026-09');

  // Collapsible sections state
  const [sectionsOpen, setSectionsOpen] = useState({
    trends: true,
    activity: true,
    netWorth: true,
    investments: true,
  });

  const toggleSection = (key) => {
    setSectionsOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Live data state
  const [dashboardData, setDashboardData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const res = await fetchWithAuth('/api/v1/dashboard/summary');
        if (res.ok) {
          const data = await res.json();
          setDashboardData(data);
        }
      } catch (err) {
        console.error('Failed to load dashboard summary for Analytics', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  // Format month title
  const monthDisplay = useMemo(() => {
    const [y, m] = selectedMonth.split('-');
    return `${y}年${m}月`;
  }, [selectedMonth]);

  // Navigate months
  const prevMonth = () => {
    const [y, m] = selectedMonth.split('-').map(Number);
    const prev = new Date(y, m - 2, 1);
    setSelectedMonth(`${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`);
  };

  const nextMonth = () => {
    const [y, m] = selectedMonth.split('-').map(Number);
    const next = new Date(y, m, 1);
    setSelectedMonth(`${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`);
  };

  const goToday = () => {
    setSelectedMonth('2026-09');
  };

  // Mock data strictly mirroring Sure reference 3.png
  const incomeCategories = [
    { name: '工资收入', count: 1, amount: 540.03, percentage: '100.0%', icon: '💰' },
  ];

  const expenseCategories = [
    { name: '其他', count: 22, amount: 1383.90, percentage: '49.2%', icon: '📦' },
    { name: '个人/转账', count: 5, amount: 473.78, percentage: '16.8%', icon: '👤' },
    { name: '购物消费', count: 30, amount: 302.59, percentage: '10.8%', icon: '🛍️' },
    { name: '超市便利', count: 25, amount: 294.52, percentage: '10.5%', icon: '🛒' },
    { name: '餐饮美食', count: 37, amount: 202.32, percentage: '7.2%', icon: '🍽️' },
    { name: '生活缴费', count: 4, amount: 126.55, percentage: '4.5%', icon: '⚡' },
    { name: '交通出行', count: 4, amount: 62.11, percentage: '2.2%', icon: '🚗' },
    { name: '待匹配退款调整', count: 6, amount: -31.17, percentage: '-1.1%', icon: '🔄', isRefund: true },
  ];

  // Net worth 30-day trend curve
  const netWorthTrend = [
    { date: 'Sep 01, 2026', value: 520000 },
    { date: 'Sep 05, 2026', value: 535000 },
    { date: 'Sep 10, 2026', value: 548000 },
    { date: 'Sep 15, 2026', value: 560000 },
    { date: 'Sep 20, 2026', value: 572000 },
    { date: 'Sep 25, 2026', value: 580000 },
    { date: 'Sep 30, 2026', value: 586866.40 },
  ];

  // Investment Accounts
  const investmentAccounts = [
    { name: '理财', type: '其他', balance: 2002.64, icon: '理' },
    { name: '中国银河证券', type: '券商', balance: 71479.64, icon: '中' },
    { name: '中国银行投资', type: '其他', balance: 85085.79, icon: '中' },
    { name: '投资', type: '其他', balance: 44452.93, icon: '投' },
    { name: '朝朝盈2号', type: '券商', balance: 60553.34, icon: '朝' },
    { name: '基金', type: '共同基金', balance: 25650.48, icon: '基' },
    { name: '工行基金', type: '其他', balance: 52647.47, icon: '工' },
    { name: '支付宝189', type: '其他', balance: 50539.79, icon: '支' },
    { name: '建行投资', type: '其他', balance: 48327.94, icon: '建' },
    { name: '平安证券', type: '券商', balance: 11882.70, icon: '平' },
    { name: '建行投资', type: '其他', balance: 13020.89, icon: '建' },
    { name: '招行理财', type: '其他', balance: 43415.13, icon: '招' },
  ];

  const handleExportCSV = () => {
    const csvContent =
      'data:text/csv;charset=utf-8,' +
      ['分类,交易记录数,金额,占总计百分比']
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
            报表
          </h1>
          <p className="text-xs text-zinc-500 mt-1">您财务健康状况的全面洞察</p>
        </div>

        <button
          onClick={() => window.print()}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs"
        >
          <Printer className="w-3.5 h-3.5" />
          <span>打印报表</span>
        </button>
      </div>

      {/* ── 2. Time Range Selector Pills & Month Navigator ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        {/* Period Pills */}
        <div className="inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl">
          {[
            { id: 'monthly', label: '按月' },
            { id: 'quarterly', label: '按季度' },
            { id: 'ytd', label: '年初至今' },
            { id: '6m', label: '最近 6 个月' },
            { id: 'custom', label: '自定义范围' },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => setPeriod(item.id)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
                period === item.id
                  ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                  : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Month Navigator: < > 2026年09月 ⌄ | 今天 */}
        <div className="flex items-center gap-2">
          <div className="flex items-center border border-zinc-200 dark:border-zinc-800 rounded-lg bg-white dark:bg-zinc-900 p-0.5">
            <button
              onClick={prevMonth}
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={nextMonth}
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 shadow-2xs">
            <span>{monthDisplay}</span>
            <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
          </button>

          <button
            onClick={goToday}
            className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 shadow-2xs"
          >
            今天
          </button>
        </div>
      </div>

      {/* ── 3. 4 Major KPI Cards (Exact 3.png) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Income */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <TrendingUp className="w-3.5 h-3.5" />
            <span>总收入</span>
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            ¥540.03
          </div>
          <div className="text-[11px] text-zinc-400 flex items-center gap-1">
            <span className="text-emerald-600 font-bold">↑ +0%</span>
            <span>与上一周期相比</span>
          </div>
        </div>

        {/* Total Expense */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <TrendingDown className="w-3.5 h-3.5" />
            <span>总支出</span>
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            ¥2,814.60
          </div>
          <div className="text-[11px] text-zinc-400 flex items-center gap-1">
            <span className="text-emerald-600 font-bold">↓ -54.4%</span>
            <span>与上一周期相比</span>
          </div>
        </div>

        {/* Net Savings */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <Layers className="w-3.5 h-3.5" />
            <span>净储蓄</span>
          </div>
          <div className="text-2xl font-bold font-mono text-rose-600 dark:text-rose-400">
            -¥2,274.57
          </div>
          <div className="text-[11px] text-zinc-400">收入减支出</div>
        </div>

        {/* Budget Performance */}
        <div className="p-4 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-xs space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-zinc-500">
            <PieIcon className="w-3.5 h-3.5" />
            <span>预算表现</span>
          </div>
          <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
            0%
          </div>
          <div className="space-y-1">
            <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-1.5 rounded-full overflow-hidden">
              <div className="bg-zinc-400 h-full w-[0%]" />
            </div>
            <div className="text-[11px] text-zinc-400">已使用预算的</div>
          </div>
        </div>
      </div>

      {/* ── 4. Section 1: 趋势与洞察 (Trends & Insights) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
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
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">趋势与洞察</h2>
          </div>
        </div>

        {sectionsOpen.trends && (
          <div className="p-5 space-y-6">
            <div>
              <h3 className="text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-3">月度明细</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left">
                  <thead>
                    <tr className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 font-medium">
                      <th className="py-2">月份</th>
                      <th className="py-2 text-right">收入</th>
                      <th className="py-2 text-right">支出</th>
                      <th className="py-2 text-right">净额</th>
                      <th className="py-2 text-right">储蓄率</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-mono">
                    <tr>
                      <td className="py-3 font-sans font-semibold text-zinc-800 dark:text-zinc-200">
                        Sep 2026 (当前)
                      </td>
                      <td className="py-3 text-right text-zinc-800 dark:text-zinc-200">¥540.03</td>
                      <td className="py-3 text-right text-zinc-800 dark:text-zinc-200">¥2,814.60</td>
                      <td className="py-3 text-right text-rose-600 font-bold">-¥2,274.57</td>
                      <td className="py-3 text-right text-rose-600 font-bold">-421.2%</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 3 Monthly Averages Boxes */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">月均收入</span>
                <div className="text-lg font-bold font-mono text-emerald-600 mt-1">¥540.03</div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">月均支出</span>
                <div className="text-lg font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  ¥2,814.60
                </div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">月均储蓄</span>
                <div className="text-lg font-bold font-mono text-rose-600 mt-1">-¥2,274.57</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 5. Section 2: 活动明细 (Activity Breakdown with Refunds!) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
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
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">活动明细</h2>
          </div>

          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={handleExportCSV}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-200 transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              <span>CSV</span>
            </button>
            <button
              onClick={() => window.open('https://docs.google.com/spreadsheets', '_blank')}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-200 transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>在 Google 表格中打开</span>
            </button>
          </div>
        </div>

        {sectionsOpen.activity && (
          <div className="p-5 space-y-6">
            {/* 1. Income Table */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800 dark:text-zinc-200">
                <TrendingUp className="w-3.5 h-3.5 text-emerald-600" />
                <span>收入: </span>
                <span className="font-mono text-emerald-600 font-bold">¥540.03</span>
              </div>

              <div className="border border-zinc-100 dark:border-zinc-800 rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-zinc-50 dark:bg-zinc-800/40 text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                      <th className="py-2.5 px-4 text-left">分类</th>
                      <th className="py-2.5 px-4 text-right">金额</th>
                      <th className="py-2.5 px-4 text-right">占总计百分比</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {incomeCategories.map((c) => (
                      <tr key={c.name} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20">
                        <td className="py-3 px-4 flex items-center gap-2">
                          <span className="w-5 h-5 rounded-md bg-amber-50 dark:bg-amber-950/40 flex items-center justify-center text-xs">
                            {c.icon}
                          </span>
                          <span className="font-medium text-zinc-800 dark:text-zinc-200">
                            {c.name} <span className="text-zinc-400 font-normal font-mono">({c.count} 条记录)</span>
                          </span>
                        </td>
                        <td className="py-3 px-4 text-right font-mono font-semibold text-emerald-600">
                          ¥{c.amount.toFixed(2)}
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-zinc-500">{c.percentage}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2. Expense Table with Refund */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800 dark:text-zinc-200">
                <TrendingDown className="w-3.5 h-3.5 text-zinc-600" />
                <span>支出: </span>
                <span className="font-mono font-bold text-zinc-900 dark:text-white">¥2,814.60</span>
              </div>

              <div className="border border-zinc-100 dark:border-zinc-800 rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-zinc-50 dark:bg-zinc-800/40 text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                      <th className="py-2.5 px-4 text-left">分类</th>
                      <th className="py-2.5 px-4 text-right">金额</th>
                      <th className="py-2.5 px-4 text-right">占总计百分比</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {expenseCategories.map((c) => (
                      <tr key={c.name} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20">
                        <td className="py-3 px-4 flex items-center gap-2">
                          <span className="w-5 h-5 rounded-md bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-xs">
                            {c.icon}
                          </span>
                          <span className="font-medium text-zinc-800 dark:text-zinc-200">
                            {c.name} <span className="text-zinc-400 font-normal font-mono">({c.count} 条记录)</span>
                          </span>
                        </td>
                        <td className="py-3 px-4 text-right font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                          {c.amount < 0 ? `-¥${Math.abs(c.amount).toFixed(2)}` : `¥${c.amount.toFixed(2)}`}
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-zinc-500">{c.percentage}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="text-[11px] text-zinc-400 px-1 pt-1">显示 134 条记录</div>
            </div>
          </div>
        )}
      </div>

      {/* ── 6. Section 3: 净资产 (Net Worth) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
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
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">净资产</h2>
          </div>
        </div>

        {sectionsOpen.netWorth && (
          <div className="p-5 space-y-6">
            {/* Top 3 Net Worth Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">当前净资产</span>
                <div className="text-xl font-bold font-mono text-emerald-600 mt-1">¥586,866.40</div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">周期变化</span>
                <div className="text-xl font-bold font-mono text-emerald-600 mt-1">
                  ¥655,418.15 <span className="text-xs font-normal">+956.1%</span>
                </div>
              </div>
              <div className="p-4 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">资产与负债</span>
                <div className="text-xl font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  ¥730,684.30 <span className="text-xs font-normal text-rose-500">- ¥143,817.90</span>
                </div>
              </div>
            </div>

            {/* Rising Green Line Chart */}
            <div className="h-44 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={netWorthTrend} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                  <XAxis dataKey="date" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis hide domain={['dataMin - 10000', 'dataMax + 10000']} />
                  <Tooltip
                    formatter={(val) => [`¥${Number(val).toLocaleString()}`, '净资产']}
                    contentStyle={{
                      backgroundColor: theme === 'dark' ? '#18181b' : '#ffffff',
                      border: '1px solid #27272a',
                      borderRadius: '8px',
                      fontSize: '11px',
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="#10b981"
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 4, fill: '#10b981' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Assets vs Liabilities Breakdown Table */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              {/* Assets column */}
              <div className="p-4 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50/30 dark:bg-zinc-800/20 space-y-2">
                <span className="font-bold text-zinc-700 dark:text-zinc-300 block mb-2">资产</span>
                <div className="flex justify-between py-1 border-b border-zinc-100 dark:border-zinc-800">
                  <span className="text-zinc-500">现金</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">¥221,625.56</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-zinc-500">投资</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">¥509,058.74</span>
                </div>
              </div>

              {/* Liabilities column */}
              <div className="p-4 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50/30 dark:bg-zinc-800/20 space-y-2">
                <span className="font-bold text-zinc-700 dark:text-zinc-300 block mb-2">负债</span>
                <div className="flex justify-between py-1 border-b border-zinc-100 dark:border-zinc-800">
                  <span className="text-zinc-500">信用卡</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">¥1,217.90</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-zinc-500">贷款</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-white">¥142,600.00</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 7. Section 4: 投资表现 (Investments) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
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
            <h2 className="text-sm font-bold text-zinc-900 dark:text-white">投资表现</h2>
          </div>
        </div>

        {sectionsOpen.investments && (
          <div className="p-5 space-y-6">
            {/* 5 Stat Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">投资组合价值</span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  ¥509,058.74
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">总回报</span>
                <div className="text-base font-bold font-mono text-zinc-400 mt-1">-</div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">本期回报</span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  ¥0.00 <span className="text-xs font-normal text-zinc-400">(0.0%)</span>
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">本期投入</span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  ¥0.00
                </div>
              </div>
              <div className="p-3.5 rounded-xl bg-zinc-50/70 dark:bg-zinc-800/40 border border-zinc-100 dark:border-zinc-800/70">
                <span className="text-[11px] text-zinc-500 font-medium">本期提取</span>
                <div className="text-base font-bold font-mono text-zinc-900 dark:text-white mt-1">
                  ¥0.00
                </div>
              </div>
            </div>

            {/* Investment Accounts Grid */}
            <div className="space-y-3">
              <h3 className="text-xs font-bold text-zinc-700 dark:text-zinc-300">投资账户</h3>
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
                        <div className="text-[10px] text-zinc-400">{acc.type}</div>
                      </div>
                    </div>

                    <div className="font-mono font-bold text-xs text-zinc-900 dark:text-white shrink-0">
                      ¥{acc.balance.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
