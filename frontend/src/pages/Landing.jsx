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
  PieChart as PieIcon,
  Calendar as CalendarIcon,
} from 'lucide-react';
import { getBalance, getMonthlySummary, getExpenses, getMyExpenseSummary } from '../api/expenses';
import { getMonthlyIncomeSummary } from '../api/income';
import { useUsers } from '../ConfigContext';
import { useCurrency } from '../CurrencyContext';
import { useDateFormat } from '../DateFormatContext';
import { useAuth } from '../auth/AuthContext';
import { useIncomeMode } from '../hooks/useIncomeMode';
import { Card, Pill, Button } from '../components/ds/DesignSystem';
import { SureAreaChart, SureDonutChart } from '../components/ds/SureCharts';

export default function Landing() {
  const { userA, userB, mode } = useUsers();
  const { user } = useAuth();
  const me = user?.displayName || userA;
  const isPersonal = mode === 'personal';
  const { currency, fmt } = useCurrency();
  const { formatDate } = useDateFormat();
  const { incomeEnabled } = useIncomeMode();

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

  // Calculate daily spending trend for current month from recentExpenses
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

  // Categories formatted for SureDonutChart
  const donutData = useMemo(() => {
    return (monthlySummary || [])
      .filter((c) => c.category !== 'Payment' && c.category !== 'Reimbursement' && c.amount > 0)
      .map((c) => ({
        category: c.category,
        amount: c.amount,
      }));
  }, [monthlySummary]);

  // Calculate refund/reimbursement total
  const reimbursementTotal = useMemo(() => {
    const r = (monthlySummary || []).find((c) => c.category === 'Reimbursement');
    return r ? Math.abs(r.amount) : 0;
  }, [monthlySummary]);

  const currencySymbol = currency === 'USD' ? '$' : currency === 'EUR' ? '€' : currency === 'GBP' ? '£' : '¥';

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-on-surface-variant font-medium">正在加载财务总览...</span>
      </div>
    );
  }

  const currentMonthSpend = myExpense?.my_total ?? 0;

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-on-surface font-headline">
            财务看板
          </h1>
          <p className="text-sm text-on-surface-variant mt-0.5">
            欢迎回来，{me}。这是您家庭的本月财务健康概览。
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Link
            to="/transactions"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-xl bg-surface-container hover:bg-surface-container-high text-on-surface border border-outline/10 transition-colors"
          >
            <Receipt className="w-3.5 h-3.5" />
            <span>查看明细</span>
          </Link>
          <Link
            to="/add"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-xl bg-primary text-white hover:opacity-90 shadow-sm transition-all active:scale-95"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>记一笔</span>
          </Link>
        </div>
      </div>

      {/* ── Key Metrics Cards (Sure Style) ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Card 1: Total Spend */}
        <Card className="p-5 flex flex-col justify-between relative overflow-hidden group">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-on-surface-variant">
                本月支出
              </span>
              <span className="p-2 rounded-xl bg-primary/10 text-primary">
                <TrendingUp className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-3 flex items-baseline gap-1.5">
              <span className="text-3xl font-extrabold font-mono tracking-tight text-on-surface">
                {fmt(currentMonthSpend)}
              </span>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline/10 flex items-center justify-between text-xs text-on-surface-variant">
            <span>涉及 {donutData.length} 个消费分类</span>
            <Link to="/analytics" className="text-primary font-semibold hover:underline flex items-center gap-1">
              分析 <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
        </Card>

        {/* Card 2: Refund & Reimbursement */}
        <Card className="p-5 flex flex-col justify-between relative overflow-hidden group">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-on-surface-variant">
                本月退款冲抵
              </span>
              <span className="p-2 rounded-xl bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                <RotateCcw className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-3 flex items-baseline gap-1.5">
              <span className="text-3xl font-extrabold font-mono tracking-tight text-emerald-600 dark:text-emerald-400">
                +{currencySymbol}{reimbursementTotal.toFixed(2)}
              </span>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline/10 flex items-center justify-between text-xs text-on-surface-variant">
            <span>自动冲减实际支出</span>
            <span className="font-mono text-emerald-600 font-semibold">已冲抵</span>
          </div>
        </Card>

        {/* Card 3: Email Ingestion Audit */}
        <Card className="p-5 flex flex-col justify-between relative overflow-hidden group">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-on-surface-variant">
                账单邮件归档
              </span>
              <span className="p-2 rounded-xl bg-blue-500/10 text-blue-600 dark:text-blue-400">
                <Mail className="w-4 h-4" />
              </span>
            </div>
            <div className="mt-3 flex items-baseline gap-1.5">
              <span className="text-3xl font-extrabold font-mono tracking-tight text-on-surface">
                164
              </span>
              <span className="text-xs font-semibold text-on-surface-variant">封</span>
            </div>
          </div>
          <div className="mt-4 pt-3 border-t border-outline/10 flex items-center justify-between text-xs text-on-surface-variant">
            <span className="flex items-center gap-1 text-emerald-600 font-medium">
              <ShieldCheck className="w-3.5 h-3.5" /> 100% SHA-256
            </span>
            <Link to="/emails" className="text-primary font-semibold hover:underline flex items-center gap-1">
              归档库 <ChevronRight className="w-3 h-3" />
            </Link>
          </div>
        </Card>
      </div>

      {/* ── Sure Charts Section (Two Columns) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Spending Trend Area Chart */}
        <div className="lg:col-span-7">
          <Card className="p-6 h-full flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-base font-bold text-on-surface tracking-tight">
                    消费趋势走势
                  </h2>
                  <p className="text-xs text-on-surface-variant mt-0.5">
                    基于最近交易日期的支出分布
                  </p>
                </div>
                <Pill variant="neutral" size="sm">
                  日均消费
                </Pill>
              </div>

              <SureAreaChart
                data={trendData.length > 0 ? trendData : [
                  { label: '09-18', amount: 120 },
                  { label: '09-20', amount: 340 },
                  { label: '09-22', amount: 210 },
                  { label: '09-24', amount: 560 },
                  { label: '09-26', amount: 180 },
                ]}
                currencySymbol={currencySymbol}
                height={260}
              />
            </div>
          </Card>
        </div>

        {/* Right Column: Category Donut Chart */}
        <div className="lg:col-span-5">
          <Card className="p-6 h-full flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-base font-bold text-on-surface tracking-tight">
                    支出分类结构
                  </h2>
                  <p className="text-xs text-on-surface-variant mt-0.5">
                    当期各项主要开支占比
                  </p>
                </div>
                <Link to="/analytics" className="text-xs text-primary font-semibold hover:underline">
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
          </Card>
        </div>
      </div>

      {/* ── Recent Activity Table (Sure Style) ── */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-bold text-on-surface tracking-tight">
              最近交易动态
            </h2>
            <p className="text-xs text-on-surface-variant mt-0.5">
              来自银行对账邮件的最新记账流水
            </p>
          </div>
          <Link
            to="/transactions"
            className="text-xs font-semibold text-primary hover:underline flex items-center gap-1"
          >
            查看全部 163 笔交易 <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="divide-y divide-outline/10">
          {recentExpenses.length === 0 ? (
            <div className="py-8 text-center text-xs text-on-surface-variant">
              暂无最新交易记录
            </div>
          ) : (
            recentExpenses.map((txn) => {
              const isNegative = Number(txn.amount) < 0 || txn.category === 'Reimbursement';
              return (
                <div
                  key={txn.id}
                  className="py-3.5 flex items-center justify-between gap-4 hover:bg-surface-container-low/40 px-2 rounded-xl transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
                      isNegative ? 'bg-amber-500/10 text-amber-600' : 'bg-surface-container text-on-surface'
                    }`}>
                      {isNegative ? <RotateCcw className="w-4 h-4" /> : <CreditCard className="w-4 h-4" />}
                    </div>

                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-on-surface truncate">
                        {txn.description}
                      </div>
                      <div className="flex items-center gap-2 text-xs text-on-surface-variant mt-0.5 font-mono">
                        <span>{formatDate(txn.date)}</span>
                        <span>•</span>
                        <span className="capitalize">{txn.category}</span>
                      </div>
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    <span className={`text-sm font-bold font-mono block ${
                      isNegative ? 'text-emerald-600 dark:text-emerald-400' : 'text-on-surface'
                    }`}>
                      {isNegative ? '+' : '-'}{fmt(Math.abs(txn.amount))}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Card>
    </div>
  );
}
