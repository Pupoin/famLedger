import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Edit2,
  AlertCircle,
  CheckCircle2,
  PieChart as PieIcon,
  Plus,
} from 'lucide-react';
import { useCurrency } from '../CurrencyContext';
import { useTheme } from '../ThemeContext';

export default function BudgetsPage() {
  const { t } = useTranslation();
  const { fmt } = useCurrency();
  const { theme } = useTheme();

  const [selectedMonth, setSelectedMonth] = useState('2026年09月');
  const [activeTab, setActiveTab] = useState('budget'); // 'budget' | 'actual'
  const [categoryFilter, setCategoryFilter] = useState('all'); // 'all' | 'over' | 'normal'

  // Over budget categories (from 4.png: 超支 · 7)
  const overBudgetCategories = [
    { name: '生活缴费', spent: 126.55, over: 126.55, icon: '⚡', color: 'rose' },
    { name: '餐饮美食', spent: 202.32, over: 202.32, icon: '🍽️', color: 'rose' },
    { name: '个人/转账', spent: 473.78, over: 473.78, icon: '👤', color: 'rose' },
    { name: '其他', spent: 1383.90, over: 1383.90, icon: '📦', color: 'rose' },
    { name: '交通出行', spent: 62.11, over: 62.11, icon: '🚗', color: 'rose' },
    { name: '购物消费', spent: 302.59, over: 302.59, icon: '🛍️', color: 'rose' },
    { name: '超市便利', spent: 294.52, over: 294.52, icon: '🛒', color: 'rose' },
  ];

  // Normal budget categories (from 4.png: 正常 · 1)
  const normalBudgetCategories = [
    {
      name: '未分类',
      spent: 0.0,
      budget: 3000.0,
      remainingDays: 4,
      dailySuggested: 750.0,
      remaining: 3000.0,
      icon: '◌',
      progress: 0,
    },
  ];

  return (
    <div className="space-y-6 pb-24 max-w-7xl mx-auto w-full max-w-full overflow-x-hidden">
      {/* ── 1. Month Navigator Header (Exact 4.png) ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center border border-zinc-200 dark:border-zinc-800 rounded-lg bg-white dark:bg-zinc-900 p-0.5">
            <button className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 shadow-2xs">
            <span>{selectedMonth}</span>
            <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
          </button>
        </div>

        <button className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 shadow-2xs">
          今天
        </button>
      </div>

      {/* ── 2. Top Summary: Circular Ring on Left + Budget/Actual on Right (4.png) ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Left: Large Circular Progress Ring */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-8 flex flex-col items-center justify-center shadow-xs">
          <div className="relative w-56 h-56 flex items-center justify-center">
            {/* SVG Progress Circle */}
            <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
              <circle
                cx="50"
                cy="50"
                r="42"
                className="stroke-zinc-100 dark:stroke-zinc-800"
                strokeWidth="7"
                fill="transparent"
              />
              <circle
                cx="50"
                cy="50"
                r="42"
                className="stroke-zinc-900 dark:stroke-white transition-all duration-500"
                strokeWidth="7"
                strokeDasharray="264"
                strokeDashoffset={264 - (264 * 2814.6) / 3000}
                strokeLinecap="round"
                fill="transparent"
              />
            </svg>

            {/* Center Content */}
            <div className="absolute inset-0 flex flex-col items-center justify-center space-y-1">
              <span className="text-xs text-zinc-400 font-medium">已花费</span>
              <span className="text-2xl sm:text-3xl font-bold font-mono text-zinc-900 dark:text-white">
                ¥2,814.60
              </span>
              <div className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-[11px] font-semibold text-zinc-600 dark:text-zinc-300 cursor-pointer hover:bg-zinc-200 transition-colors">
                <span>占 ¥3,000.00</span>
                <Edit2 className="w-2.5 h-2.5 ml-0.5" />
              </div>
            </div>
          </div>
        </div>

        {/* Right: Budget Overview Card */}
        <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 flex flex-col justify-between shadow-xs space-y-6">
          {/* Top Segmented Tabs: 预算 | 实际 */}
          <div className="flex justify-end">
            <div className="inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl w-48">
              <button
                onClick={() => setActiveTab('budget')}
                className={`flex-1 py-1.5 text-xs font-semibold rounded-lg text-center transition-all ${
                  activeTab === 'budget'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900'
                }`}
              >
                预算
              </button>
              <button
                onClick={() => setActiveTab('actual')}
                className={`flex-1 py-1.5 text-xs font-semibold rounded-lg text-center transition-all ${
                  activeTab === 'actual'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900'
                }`}
              >
                实际
              </button>
            </div>
          </div>

          {/* Projected Income Section */}
          <div className="space-y-1">
            <span className="text-xs text-zinc-400 font-medium">预期收入</span>
            <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">¥0.00</div>
            <div className="flex items-center justify-between text-xs pt-1">
              <span className="text-zinc-500 font-mono">已赚 ¥540.03</span>
              <span className="text-emerald-600 font-semibold font-mono">超出 ¥540.03</span>
            </div>
          </div>

          {/* Budget Progress Bar */}
          <div className="space-y-2">
            <span className="text-xs text-zinc-400 font-medium">预算</span>
            <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
              ¥3,000.00
            </div>
            {/* Dark progress bar */}
            <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
              <div
                className="bg-zinc-900 dark:bg-white h-full rounded-full transition-all duration-500"
                style={{ width: `${(2814.6 / 3000) * 100}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-xs pt-1">
              <span className="text-zinc-500 font-mono">已花 ¥2,814.60</span>
              <span className="text-zinc-900 dark:text-zinc-100 font-semibold font-mono">
                剩余 ¥185.40
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── 3. Category Breakdown Section (Exact 4.png) ── */}
      <div className="space-y-4">
        {/* Section Header with Filters & Edit Button */}
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-zinc-900 dark:text-white">分类</h2>

          <div className="flex items-center gap-3">
            {/* Filter Pills: 全部 | 超支 | 正常 */}
            <div className="inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl">
              {[
                { id: 'all', label: '全部' },
                { id: 'over', label: '超支' },
                { id: 'normal', label: '正常' },
              ].map((f) => (
                <button
                  key={f.id}
                  onClick={() => setCategoryFilter(f.id)}
                  className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                    categoryFilter === f.id
                      ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                      : 'text-zinc-500 hover:text-zinc-900'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>

            {/* Edit Button */}
            <button className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 shadow-2xs">
              <Edit2 className="w-3 h-3" />
              <span>编辑</span>
            </button>
          </div>
        </div>

        {/* Group 1: 超支 · 7 */}
        {(categoryFilter === 'all' || categoryFilter === 'over') && (
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs space-y-5">
            <div className="flex items-center justify-between text-xs text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800 pb-2">
              <span>超支 · 7</span>
              <span>金额</span>
            </div>

            <div className="space-y-6">
              {overBudgetCategories.map((cat, idx) => (
                <div key={idx} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-600 flex items-center justify-center text-xs">
                        {cat.icon}
                      </span>
                      <span className="font-bold text-xs text-zinc-900 dark:text-white">
                        {cat.name}
                      </span>
                    </div>

                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400">
                      <AlertCircle className="w-3 h-3" />
                      <span>超出预算</span>
                    </span>
                  </div>

                  {/* Red Solid Progress Bar */}
                  <div className="w-full bg-rose-100 dark:bg-rose-950/40 h-2 rounded-full overflow-hidden">
                    <div className="bg-rose-600 h-full w-full rounded-full" />
                  </div>

                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-zinc-500">已花费: ¥{cat.spent.toFixed(2)}</span>
                    <span className="text-rose-600 font-bold">超出: ¥{cat.over.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Group 2: 正常 · 1 */}
        {(categoryFilter === 'all' || categoryFilter === 'normal') && (
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs space-y-4">
            <div className="flex items-center justify-between text-xs text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800 pb-2">
              <span>正常 · 1</span>
              <span>金额</span>
            </div>

            {normalBudgetCategories.map((cat, idx) => (
              <div key={idx} className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 flex items-center justify-center text-xs">
                      {cat.icon}
                    </span>
                    <span className="font-bold text-xs text-zinc-900 dark:text-white">
                      {cat.name}
                    </span>
                  </div>

                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="w-3 h-3" />
                    <span>进展良好</span>
                  </span>
                </div>

                {/* Green Progress Bar */}
                <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div className="bg-emerald-500 h-full w-[2%] rounded-full" />
                </div>

                <div className="flex items-center justify-between text-xs font-mono">
                  <div className="flex items-center gap-2 text-zinc-500">
                    <span>已花费: ¥{cat.spent.toFixed(2)}</span>
                    <span>预算: ¥{cat.budget.toFixed(2)}</span>
                    <span className="text-zinc-400">
                      剩余 {cat.remainingDays} 天，建议每天花费 ¥{cat.dailySuggested.toFixed(2)}
                    </span>
                  </div>
                  <span className="text-emerald-600 font-bold">
                    剩余: ¥{cat.remaining.toFixed(2)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
