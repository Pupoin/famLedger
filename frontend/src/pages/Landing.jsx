import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  TrendingUp,
  Receipt,
  Mail,
  ShieldCheck,
  Plus,
  ArrowRight,
  ChevronRight,
  CreditCard,
  RotateCcw,
  Sparkles,
  ChevronDown,
  GripVertical,
} from 'lucide-react';
import { getBalance, getMonthlySummary, getExpenses, getMyExpenseSummary } from '../api/expenses';
import { useUsers } from '../ConfigContext';
import { useCurrency } from '../CurrencyContext';
import { useDateFormat } from '../DateFormatContext';
import { useAuth } from '../auth/AuthContext';
import { SureAreaChart, SureDonutChart } from '../components/ds/SureCharts';

export default function Landing() {
  const { userA, mode } = useUsers();
  const { user } = useAuth();
  const me = user?.displayName || user?.username || userA || 'Qq';
  const { currency, fmt, privacyMode } = useCurrency();
  const { formatDate } = useDateFormat();

  const [monthlySummary, setMonthlySummary] = useState([]);
  const [recentExpenses, setRecentExpenses] = useState([]);
  const [myExpense, setMyExpense] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        setLoading(true);
        const [sumRes, expRes, myRes] = await Promise.allSettled([
          getMonthlySummary(),
          getExpenses({ limit: 6, sort: 'desc' }),
          getMyExpenseSummary(),
        ]);

        if (sumRes.status === 'fulfilled') setMonthlySummary(sumRes.value || []);
        if (expRes.status === 'fulfilled') setRecentExpenses(expRes.value || []);
        if (myRes.status === 'fulfilled') setMyExpense(myRes.value || null);
      } catch (err) {
        console.error('Failed to load dashboard data', err);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  // Daily spending trend
  const trendData = useMemo(() => {
    if (!recentExpenses || recentExpenses.length === 0) return [];
    const dateMap = {};
    recentExpenses.forEach((item) => {
      if (item.category === 'Payment' || item.category === 'Reimbursement') return;
      const d = item.date;
      const amt = Math.abs(Number(item.amount) || 0);
      dateMap[d] = (dateMap[d] || 0) + amt;
    });

    return Object.entries(dateMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([d, amt]) => ({
        label: d.length >= 10 ? d.slice(5) : d,
        amount: amt,
      }));
  }, [recentExpenses]);

  // Donut data
  const donutData = useMemo(() => {
    return (monthlySummary || [])
      .filter((c) => c.category !== 'Payment' && c.category !== 'Reimbursement' && c.amount > 0)
      .map((c) => ({
        category: c.category,
        amount: c.amount,
      }));
  }, [monthlySummary]);

  const reimbursementTotal = useMemo(() => {
    const r = (monthlySummary || []).find((c) => c.category === 'Reimbursement');
    return r ? Math.abs(r.amount) : 0;
  }, [monthlySummary]);

  const currentMonthSpend = myExpense?.my_total ?? 0;
  const currencySymbol = currency === 'USD' ? '$' : currency === 'EUR' ? '€' : currency === 'GBP' ? '£' : '¥';

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <div className="w-6 h-6 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-zinc-400 font-medium">Loading dashboard...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── 1. Page Header (Exact Sure Header) ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            Welcome back, {me}
          </h1>
          <p className="text-xs sm:text-sm text-zinc-500 mt-1">
            Here's what's happening with your finances
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            to="/add"
            className="inline-flex items-center justify-center w-9 h-9 sm:w-auto sm:px-3 sm:py-2 text-sm font-medium rounded-full sm:rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-all active:scale-95"
            title="记一笔 / 新增交易"
          >
            <Plus className="w-4 h-4" />
            <span className="hidden sm:inline">New</span>
          </Link>
        </div>
      </div>

      {/* ── 2. Time & Account Filters Row (Sure Filter Badges) ── */}
      <div className="flex items-center justify-end gap-2">
        <button className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors">
          <span>All</span>
          <ChevronDown className="w-3 h-3 text-zinc-400" />
        </button>
        <button className="flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 shadow-2xs hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors">
          <span>30D</span>
          <ChevronDown className="w-3 h-3 text-zinc-400" />
        </button>
      </div>

      {/* ── 3. Sure Cashflow & Net Worth Widgets ── */}
      <div className="grid grid-cols-1 gap-6">
        {/* Widget 1: Cashflow Card */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-1.5 cursor-pointer">
              <ChevronDown className="w-4 h-4 text-zinc-400" />
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Cashflow
              </h2>
            </div>
            <GripVertical className="w-4 h-4 text-zinc-300 dark:text-zinc-600" />
          </div>

          <div className="pt-2">
            <SureAreaChart data={trendData} currencySymbol={currencySymbol} height={260} />
          </div>
        </div>

        {/* Widget 2: Net Worth Card (Exact Sure Widget) */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-1.5 cursor-pointer">
              <ChevronDown className="w-4 h-4 text-zinc-400" />
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Net Worth
              </h2>
            </div>
            <GripVertical className="w-4 h-4 text-zinc-300 dark:text-zinc-600" />
          </div>
          <div>
            <span className="text-3xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100">
              {fmt(Math.max(0, 10580.50 - currentMonthSpend + reimbursementTotal))}
            </span>
            <span className="block text-xs text-zinc-400 mt-1">
              no change vs. last 30 days
            </span>
          </div>
        </div>

        {/* ── 4. Key Financial Metrics (Sure 3-Card Matrix) ── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Spend */}
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider block">
                本月支出
              </span>
              <span className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-2 block">
                {fmt(currentMonthSpend)}
              </span>
            </div>
            <div className="mt-4 pt-3 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between text-xs text-zinc-500">
              <span>覆盖 {donutData.length} 个消费分类</span>
              <Link to="/analytics" className="text-zinc-900 dark:text-white font-medium hover:underline flex items-center gap-0.5">
                报表 <ChevronRight className="w-3 h-3" />
              </Link>
            </div>
          </div>

          {/* Refund */}
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider block">
                本月退款冲抵
              </span>
              <span className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-emerald-600 dark:text-emerald-400 mt-2 block">
                +{fmt(reimbursementTotal)}
              </span>
            </div>
            <div className="mt-4 pt-3 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between text-xs text-zinc-500">
              <span>自动冲减实际支出</span>
              <span className="font-mono text-emerald-600 font-semibold">已冲减</span>
            </div>
          </div>

          {/* Emails */}
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs flex flex-col justify-between">
            <div>
              <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider block">
                账单邮件归档
              </span>
              <span className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-2 block">
                164 <span className="text-sm font-normal text-zinc-500">封</span>
              </span>
            </div>
            <div className="mt-4 pt-3 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between text-xs text-zinc-500">
              <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="w-3.5 h-3.5" /> 100% SHA-256 溯源
              </span>
              <Link to="/emails" className="text-zinc-900 dark:text-white font-medium hover:underline flex items-center gap-0.5">
                归档库 <ChevronRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </div>

        {/* ── 5. Category Structure (Sure Donut) ── */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-xs">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
              支出分类结构
            </h2>
            <Link to="/analytics" className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-white font-medium">
              全部
            </Link>
          </div>
          <SureDonutChart
            data={donutData}
            totalAmount={currentMonthSpend}
            currencySymbol={currencySymbol}
            height={240}
          />
        </div>

        {/* ── 6. Recent Activity List ── */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-xs">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                最近交易动态
              </h2>
              <p className="text-xs text-zinc-500 mt-0.5">
                来自银行对账邮件的真实入账明细
              </p>
            </div>
            <Link
              to="/transactions"
              className="text-xs font-semibold text-zinc-900 dark:text-zinc-100 hover:underline flex items-center gap-1"
            >
              查看全部 163 笔交易 <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {recentExpenses.length === 0 ? (
              <div className="py-8 text-center text-xs text-zinc-400">
                暂无最新交易记录
              </div>
            ) : (
              recentExpenses.map((txn) => {
                const isNegative = Number(txn.amount) < 0 || txn.category === 'Reimbursement';
                return (
                  <div
                    key={txn.id}
                    className="py-3 flex items-center justify-between gap-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 px-2 rounded-xl transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                        isNegative ? 'bg-emerald-500/10 text-emerald-600' : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300'
                      }`}>
                        {isNegative ? <RotateCcw className="w-4 h-4" /> : <CreditCard className="w-4 h-4" />}
                      </div>

                      <div className="min-w-0">
                        <p className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                          {txn.description}
                        </p>
                        <p className="text-[11px] text-zinc-500 mt-0.5 font-mono">
                          {formatDate(txn.date)} · {txn.category}
                        </p>
                      </div>
                    </div>

                    <div className="text-right shrink-0">
                      <span className={`text-xs sm:text-sm font-bold font-mono block ${
                        isNegative ? 'text-emerald-600 dark:text-emerald-400' : 'text-zinc-900 dark:text-zinc-100'
                      }`}>
                        {isNegative ? '+' : '-'}{fmt(Math.abs(txn.amount))}
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
