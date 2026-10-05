import { categoryLabel, tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronLeft, ChevronRight, Edit2, AlertCircle, CheckCircle2, X, Plus, Trash2 } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';
import { formatCurrency } from '../utils/currency';
import { useTheme } from '../ThemeContext';
import { useToast } from '../ToastContext';
import { apiErrorMessage } from '../api/errorMessages';
import { allocateBudgetAmounts } from '../utils/budgetAllocation';
import { Button } from '../components/ds/DesignSystem';

const getCurrentMonthStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

export default function BudgetsPage() {
  useLocale();
  const { t } = useTranslation();
  const { privacyMode, symbol } = useCurrency();
  const { showToast } = useToast();
  const { theme } = useTheme();

  const [selectedMonth, setSelectedMonth] = useState(getCurrentMonthStr);
  const [activeTab, setActiveTab] = useState('budget'); // 'budget' | 'actual'
  const [categoryFilter, setCategoryFilter] = useState('all'); // 'all' | 'over' | 'normal'
  const [loading, setLoading] = useState(true);
  const [budgetData, setBudgetData] = useState(null);
  const fmt = (value) => privacyMode ? "••••" : formatCurrency(value, budgetData?.currency_symbol || "¥");

  // Edit Budget Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState({
    total_budget: 10000,
    expected_income: 20000,
    category_percentages: {},
  });
  const [availableCategories, setAvailableCategories] = useState([]);
  const [newCategory, setNewCategory] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saving, setSaving] = useState(false);
  const [lastEditedCategory, setLastEditedCategory] = useState('');
  const [deleteCategory, setDeleteCategory] = useState(null);
  const longPressTimer = useRef(null);
  const pressStart = useRef(null);
  const menuOpeningPress = useRef(false);
  const cancelCategoryPress = () => { clearTimeout(longPressTimer.current); longPressTimer.current = null; pressStart.current = null; };
  const removeBudgetCategory = cname => {
    setEditForm(p => { const percentages = { ...p.category_percentages }; delete percentages[cname];
      return { ...p, category_percentages: percentages }; });
    setDeleteCategory(null);
  };
  const startCategoryPress = (event, cname) => {
    if (event.pointerType !== 'touch' || event.target.closest('input, button, select')) return;
    cancelCategoryPress();
    pressStart.current = { x: event.clientX, y: event.clientY };
    longPressTimer.current = setTimeout(() => { menuOpeningPress.current = true; setDeleteCategory(cname); cancelCategoryPress(); }, 550);
  };
  const moveCategoryPress = event => {
    if (pressStart.current && Math.hypot(event.clientX - pressStart.current.x, event.clientY - pressStart.current.y) > 10) cancelCategoryPress();
  };
  useEffect(() => () => clearTimeout(longPressTimer.current), []);
  useEffect(() => { if (!isEditModalOpen) { cancelCategoryPress(); setDeleteCategory(null); } }, [isEditModalOpen]);
  useEffect(() => {
    if (!isEditModalOpen) return;
    const roots = [document.documentElement, document.body];
    const previousOverflow = roots.map(root => root.style.overflow);
    roots.forEach(root => { root.style.overflow = 'hidden'; });
    return () => roots.forEach((root, index) => { root.style.overflow = previousOverflow[index]; });
  }, [isEditModalOpen]);
  const categoryAmounts = allocateBudgetAmounts(editForm.total_budget, editForm.category_percentages);
  const allocatedPercent = Object.values(editForm.category_percentages).reduce((sum, value) => sum + Math.round(Number(value || 0) * 100), 0) / 100;
  const allocatedAmount = Object.values(categoryAmounts).reduce((sum, value) => sum + Math.round(value * 100), 0) / 100;
  const unselectedCategories = availableCategories.filter(category => !Object.hasOwn(editForm.category_percentages, category.name));
  const categoryIcon = name => availableCategories.find(category => category.name === name)?.icon
    || budgetData?.all_categories?.find(category => category.name === name)?.icon || '📦';
  const limitCategory = Object.hasOwn(editForm.category_percentages, lastEditedCategory) ? lastEditedCategory : Object.keys(editForm.category_percentages).at(-1);
  const maximumPercent = Math.max(0, 10000 - Math.round(allocatedPercent * 100)
    + Math.round(Number(editForm.category_percentages[limitCategory] || 0) * 100)) / 100;

  const openBudgetEditor = () => {
    setEditForm({ total_budget: budgetData?.total_budget ?? 10000, expected_income: budgetData?.expected_income ?? 20000,
      category_percentages: { ...budgetData?.category_percentages } });
    setNewCategory('');
    setLastEditedCategory('');
    setSaveError('');
    setIsEditModalOpen(true);
  };

  const loadBudgets = async () => {
    try {
      setLoading(true);
      const res = await fetchWithAuth(`/api/v1/budgets/summary?month=${selectedMonth}`);
      if (res.ok) {
        const data = await res.json();
        setBudgetData(data);
        setEditForm({
          total_budget: data.total_budget ?? 10000,
          expected_income: data.expected_income ?? 20000,
          category_percentages: { ...data.category_percentages },
        });
      }
    } catch (err) {
      console.error('Failed to load budget data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBudgets();
    window.addEventListener('transaction-updated', loadBudgets);
    return () => window.removeEventListener('transaction-updated', loadBudgets);
  }, [selectedMonth]);

  useEffect(() => {
    if (!isEditModalOpen) return;
    let cancelled = false;
    fetchWithAuth('/api/v1/categories?category_type=expense').then(async res => {
      if (!res.ok) throw new Error('categories');
      const data = await res.json();
      if (!cancelled) setAvailableCategories((Array.isArray(data) ? data : data.categories || data.items || [])
        .filter(category => category.category_type !== 'income'));
    }).catch(() => { if (!cancelled) setSaveError(tx("无法加载分类，请稍后重试")); });
    return () => { cancelled = true; };
  }, [isEditModalOpen]);

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
    setSelectedMonth(getCurrentMonthStr());
  };

  const handleSaveBudgetSettings = async (e) => {
    e.preventDefault();
    if (saving) return;
    if (allocatedPercent > 100) { setSaveError(tx("分类预算比例合计不能超过 100%")); return; }
    setSaveError('');
    setSaving(true);
    try {
      const res = await fetchWithAuth('/api/v1/budgets/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });
      if (res.ok) {
        setIsEditModalOpen(false);
        showToast(tx("预算设置已保存"), 'success');
        loadBudgets();
      } else {
        const error = await res.json().catch(() => ({}));
        setSaveError(apiErrorMessage(error.detail, tx("保存预算失败，请重试")));
      }
    } catch {
      setSaveError(tx("保存预算失败，请重试"));
    } finally {
      setSaving(false);
    }
  };

  const totalBudget = budgetData?.total_budget ?? 10000;
  const totalSpent = budgetData?.total_spent || 0;
  const totalRemaining = budgetData?.total_remaining || 0;
  const totalOver = budgetData?.total_over || 0;
  const isTotalOver = budgetData?.is_total_over || false;
  const earnedIncome = budgetData?.earned_income || 0;
  const expectedIncome = budgetData?.expected_income ?? 20000;
  const incomeDiff = budgetData?.income_diff || 0;

  const overBudgetCategories = budgetData?.over_categories || [];
  const normalBudgetCategories = budgetData?.normal_categories || [];

  const progressFraction = totalBudget > 0 ? Math.min(1.0, totalSpent / totalBudget) : 0;
  const strokeOffset = 264 - 264 * progressFraction;

  return (
    <div className="space-y-6 pb-24 max-w-7xl mx-auto w-full max-w-full overflow-x-hidden animate-in fade-in duration-200">
      {/* ── 1. Month Navigator Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex items-center border border-zinc-200 dark:border-zinc-800 rounded-lg bg-white dark:bg-zinc-900 p-0.5 shadow-2xs">
            <button
              onClick={prevMonth}
              title={tx("上一月")}
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={nextMonth}
              title={tx("下一月")}
              className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 shadow-2xs">
            <span>{tx(monthDisplay)}</span>
          </div>
        </div>

        <button
          onClick={goToday}
          className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs transition-colors"
        >{tx("当月")}</button>
      </div>

      {/* ── 2. Top Summary: Circular Ring on Left + Budget/Actual on Right ── */}
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
                className={`transition-all duration-500 ${
                  isTotalOver ? 'stroke-rose-500' : 'stroke-zinc-900 dark:stroke-white'
                }`}
                strokeWidth="7"
                strokeDasharray="264"
                strokeDashoffset={strokeOffset}
                strokeLinecap="round"
                fill="transparent"
              />
            </svg>

            {/* Center Content */}
            <div className="absolute inset-0 flex flex-col items-center justify-center space-y-1">
              <span className="text-xs text-zinc-400 font-medium">{tx("已花费 (净支出)")}</span>
              <span
                className={`text-2xl sm:text-3xl font-bold font-mono ${
                  isTotalOver ? 'text-rose-600 dark:text-rose-400' : 'text-zinc-900 dark:text-white'
                }`}
              >
                {fmt(totalSpent)}
              </span>
              <button
                type="button"
                onClick={openBudgetEditor}
                className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-[11px] font-semibold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
              >
                <span>{tx("占 ¥").replace("¥", "")} {fmt(totalBudget)}</span>
                <Edit2 className="w-2.5 h-2.5 ml-0.5" />
              </button>
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
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
                }`}
              >{tx("预算模式")}</button>
              <button
                onClick={() => setActiveTab('actual')}
                className={`flex-1 py-1.5 text-xs font-semibold rounded-lg text-center transition-all ${
                  activeTab === 'actual'
                    ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
                }`}
              >{tx("实际收支")}</button>
            </div>
          </div>

          {activeTab === 'budget' ? (
            <>
              {/* Projected Income Section */}
              <div className="space-y-1">
                <span className="text-xs text-zinc-400 font-medium">{tx("预期收入")}</span>
                <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
                  {fmt(expectedIncome)}
                </div>
                <div className="flex items-center justify-between text-xs pt-1">
                  <span className="text-zinc-500 font-mono">{tx("已入账 ¥").replace("¥", "")} {fmt(earnedIncome)}
                  </span>
                  <span
                    className={`font-semibold font-mono ${
                      incomeDiff >= 0 ? 'text-emerald-600' : 'text-zinc-400'
                    }`}
                  >
                    {incomeDiff >= 0 ? tx("达标 +¥{p0}", {p0: fmt(incomeDiff)}).replace("¥", "") : tx("还差 ¥{p0}", {p0: fmt(Math.abs(incomeDiff))}).replace("¥", "")}
                  </span>
                </div>
              </div>

              {/* Budget Progress Bar */}
              <div className="space-y-2">
                <span className="text-xs text-zinc-400 font-medium">{tx("总预算")}</span>
                <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
                  {fmt(totalBudget)}
                </div>
                {/* Progress bar */}
                <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      isTotalOver ? 'bg-rose-500' : 'bg-zinc-900 dark:bg-white'
                    }`}
                    style={{ width: `${Math.min(100, (totalSpent / (totalBudget || 1)) * 100)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between text-xs pt-1">
                  <span className="text-zinc-500 font-mono">{tx("已花 ¥").replace("¥", "")} {fmt(totalSpent)}
                  </span>
                  <span
                    className={`font-semibold font-mono ${
                      isTotalOver ? 'text-rose-600' : 'text-zinc-900 dark:text-zinc-100'
                    }`}
                  >
                    {isTotalOver ? tx("超支 ¥{p0}", {p0: fmt(totalOver)}).replace("¥", "") : tx("剩余 ¥{p0}", {p0: fmt(totalRemaining)}).replace("¥", "")}
                  </span>
                </div>
              </div>
            </>
          ) : (
            <>
              {/* Actual Financial Performance */}
              <div className="space-y-1">
                <span className="text-xs text-zinc-400 font-medium">{tx("当月外部净收入")}</span>
                <div className="text-2xl font-bold font-mono text-emerald-600 dark:text-emerald-400">
                  {fmt(earnedIncome)}
                </div>
                <div className="text-xs text-zinc-400">{tx("纯增量劳动与理财所得")}</div>
              </div>

              <div className="space-y-2">
                <span className="text-xs text-zinc-400 font-medium">{tx("实际净支出与结余")}</span>
                <div className="text-2xl font-bold font-mono text-zinc-900 dark:text-white">
                  {fmt(totalSpent)}
                </div>
                <div className="flex items-center justify-between text-xs pt-1">
                  <span className="text-zinc-500 font-mono">{tx("当月净结余: ¥").replace("¥", "")} {fmt(earnedIncome - totalSpent)}
                  </span>
                  <span className="text-emerald-600 font-semibold font-mono">{tx("储蓄率")} {earnedIncome > 0 ? Math.round(((earnedIncome - totalSpent) / earnedIncome) * 100) : 0}%
                  </span>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── 3. Category Breakdown Section ── */}
      <div className="space-y-4">
        {/* Section Header with Filters & Edit Button */}
        <div data-testid="budget-category-header" className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center justify-between gap-2 sm:contents">
            <h2 className="text-base sm:text-lg font-bold text-zinc-900 dark:text-white">
              <span className="sm:hidden">{tx("分类预算执行")}</span>
              <span className="hidden sm:inline">{tx("分类预算执行情况")}</span>
            </h2>
            <button onClick={openBudgetEditor} className="sm:order-3 shrink-0 inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs transition-colors whitespace-nowrap">
              <Edit2 className="w-3 h-3" />
              <span>{tx("调整预算")}</span>
            </button>
          </div>

          <div className="sm:order-2 w-full sm:w-auto">
            {/* Filter Pills: 全部 | 超支 | 正常 */}
            <div data-testid="budget-category-filters" role="group" aria-label={tx("分类预算执行")} className="grid grid-cols-3 w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800 overflow-hidden divide-x divide-zinc-200 dark:divide-zinc-700">
              {[
                { id: 'all', label: '全部', count: overBudgetCategories.length + normalBudgetCategories.length },
                { id: 'over', label: '超支', count: overBudgetCategories.length },
                { id: 'normal', label: '正常', count: normalBudgetCategories.length },
              ].map((f) => (
                <button
                  key={f.id}
                  aria-pressed={categoryFilter === f.id}
                  onClick={() => setCategoryFilter(f.id)}
                  className={`flex items-center justify-center gap-2 px-3 py-2 text-xs font-semibold whitespace-nowrap transition-colors ${
                    categoryFilter === f.id
                      ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                      : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-300'
                  }`}
                >
                  <span>{tx(f.label)}</span><span className="tabular-nums">{f.count}</span>
                </button>
              ))}
            </div>

          </div>
        </div>

        {/* Group 1: 超支 */}
        {(categoryFilter === 'all' || categoryFilter === 'over') && overBudgetCategories.length > 0 && (
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs space-y-5">
            <div className="flex items-center justify-between text-xs text-rose-500 font-semibold border-b border-zinc-100 dark:border-zinc-800 pb-2">
              <span>{tx("超支分类 ·")} {overBudgetCategories.length}</span>
              <span>{tx("执行状态")}</span>
            </div>

            <div className="space-y-6">
              {overBudgetCategories.map((cat, idx) => (
                <div key={idx} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-7 h-7 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-600 flex items-center justify-center text-sm shadow-2xs">
                        {cat.icon || '📦'}
                      </span>
                      <span className="font-bold text-sm text-zinc-900 dark:text-white">
                        {categoryLabel(cat.name)}
                      </span>
                    </div>

                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-600 dark:text-rose-400">
                      <AlertCircle className="w-3.5 h-3.5" />
                      <span>{tx("超出 ¥").replace("¥", "")} {fmt(cat.over)}</span>
                    </span>
                  </div>

                  {/* Red Solid Progress Bar */}
                  <div className="w-full bg-rose-100 dark:bg-rose-950/40 h-2 rounded-full overflow-hidden">
                    <div className="bg-rose-600 h-full w-full rounded-full" />
                  </div>

                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-zinc-500">{tx("已花费: ¥").replace("¥", "")} {fmt(cat.spent)}</span>
                    <span className="text-zinc-400">{tx("设定预算: ¥").replace("¥", "")} {fmt(cat.budget)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Group 2: 正常 */}
        {(categoryFilter === 'all' || categoryFilter === 'normal') && normalBudgetCategories.length > 0 && (
          <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-xs space-y-5">
            <div className="flex items-center justify-between text-xs text-emerald-600 font-semibold border-b border-zinc-100 dark:border-zinc-800 pb-2">
              <span>{tx("正常预算 ·")} {normalBudgetCategories.length}</span>
              <span>{tx("执行进度")}</span>
            </div>

            <div className="space-y-6">
              {normalBudgetCategories.map((cat, idx) => (
                <div key={idx} className="space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="w-7 h-7 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 flex items-center justify-center text-sm shadow-2xs">
                        {cat.icon || '📦'}
                      </span>
                      <span className="font-bold text-sm text-zinc-900 dark:text-white">
                        {categoryLabel(cat.name)}
                      </span>
                    </div>

                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>{tx("良好 (进度")} {cat.progress}%)</span>
                    </span>
                  </div>

                  {/* Green Progress Bar */}
                  <div className="w-full bg-zinc-100 dark:bg-zinc-800 h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-emerald-500 h-full rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(100, cat.progress)}%` }}
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between text-xs font-mono gap-2">
                    <div className="flex items-center gap-3 text-zinc-500">
                      <span>{tx("已花费: ¥").replace("¥", "")} {fmt(cat.spent)}</span>
                      <span>{tx("预算: ¥").replace("¥", "")} {fmt(cat.budget)}</span>
                      {cat.remaining_days > 0 && (
                        <span className="text-zinc-400">{tx("剩余")} {cat.remaining_days} {tx("天，建议日限 ¥").replace("¥", "")} {fmt(cat.daily_suggested)}
                        </span>
                      )}
                    </div>
                    <span className="text-emerald-600 font-bold">{tx("剩余: ¥").replace("¥", "")} {fmt(cat.remaining)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── 4. Edit Budget Modal ── */}
      {isEditModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4 bg-black/50 backdrop-blur-xs overflow-hidden overscroll-none animate-in fade-in duration-150">
          <div role="dialog" aria-modal="true" aria-labelledby="budget-settings-title" className="relative w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 p-3 sm:p-6 space-y-5 max-h-[90vh] overflow-y-auto overscroll-contain">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
              <h3 id="budget-settings-title" className="text-base font-bold text-zinc-900 dark:text-white">{tx("调整家庭预算设定")}</h3>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(false)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSaveBudgetSettings} className="space-y-4">
              {saveError && <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">{tx(saveError)}</p>}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="budget-total" className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 mb-1 block">{tx("每月总预算")} ({budgetData?.currency_symbol || symbol})</label>
                  <input
                    id="budget-total"
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={editForm.total_budget}
                    onChange={(e) => setEditForm((p) => ({ ...p, total_budget: Number(e.target.value) }))}
                    className="w-full px-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-zinc-900"
                  />
                </div>
                <div>
                  <label htmlFor="budget-income" className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 mb-1 block">{tx("预期月收入")} ({budgetData?.currency_symbol || symbol})</label>
                  <input
                    id="budget-income"
                    type="number"
                    min="0"
                    step="0.01"
                    required
                    value={editForm.expected_income}
                    onChange={(e) => setEditForm((p) => ({ ...p, expected_income: Number(e.target.value) }))}
                    className="w-full px-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-zinc-900"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 mb-2 block">{tx("分项分类限额设定 (%)")}</label>
                <div data-testid="budget-category-scroll" className="space-y-2.5 max-h-72 overflow-y-auto overscroll-contain pr-1" onScroll={cancelCategoryPress}>
                  {Object.keys(editForm.category_percentages).map(cname => (
                    <div key={cname} data-testid="budget-category-row" data-category={cname}
                      onPointerDown={event => startCategoryPress(event, cname)} onPointerMove={moveCategoryPress}
                      onPointerUp={cancelCategoryPress} onPointerCancel={cancelCategoryPress}
                      onContextMenu={event => { if (window.innerWidth < 640 && !event.target.closest('input')) event.preventDefault(); }}
                      className="grid grid-cols-[minmax(0,1fr)_auto_4.25rem] sm:grid-cols-[minmax(0,1fr)_auto_4.25rem_1.25rem] items-center gap-1.5 py-2 border-b border-zinc-100 dark:border-zinc-800 select-none">
                      <span title={categoryLabel(cname)} className="min-w-0 flex items-center gap-1 text-xs font-medium text-zinc-800 dark:text-zinc-200">
                        <span data-testid="budget-category-icon" className="shrink-0">{categoryIcon(cname)}</span>
                        <span className="truncate">{categoryLabel(cname)}</span>
                      </span>
                      <output data-testid="budget-category-amount" className="text-xs font-mono text-zinc-800 dark:text-zinc-200 whitespace-nowrap text-right">{fmt(categoryAmounts[cname])}</output>
                      <div className="flex items-center gap-1">
                          <input type="number" min="0" max="100" step="0.01" required aria-label={tx("分类比例 {p0}", { p0: categoryLabel(cname) })}
                            value={editForm.category_percentages[cname]} onChange={e => {
                              setLastEditedCategory(cname);
                              setEditForm(p => ({ ...p, category_percentages: { ...p.category_percentages, [cname]: e.target.value } }));
                            }}
                            className="w-14 px-1 py-1.5 text-right font-mono text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-white select-text [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" />
                          <span className="text-xs text-zinc-500 dark:text-zinc-400">%</span>
                      </div>
                      <button type="button" aria-label={tx("移除分类 {p0}", { p0: categoryLabel(cname) })} onClick={() => removeBudgetCategory(cname)}
                        className="hidden sm:block p-0.5 rounded text-zinc-400 hover:text-rose-600 dark:hover:text-rose-400"><Trash2 className="w-3.5 h-3.5" /></button>
                    </div>
                  ))}
                </div>
                <div className="flex items-center gap-2 mt-3">
                  <select data-testid="budget-add-category" aria-label={tx("选择预算分类")} value={newCategory} onChange={e => setNewCategory(e.target.value)}
                    className="min-w-0 flex-1 px-2 py-2 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100">
                    <option value="">{tx("选择预算分类")}</option>
                    {unselectedCategories.map(category => <option key={category.name} value={category.name}>{category.icon || '📦'} {categoryLabel(category.name)}</option>)}
                  </select>
                  <Button size="sm" variant="secondary" disabled={!newCategory} icon={Plus} onClick={() => {
                    setEditForm(p => ({ ...p, category_percentages: { ...p.category_percentages, [newCategory]: 0 } }));
                    setNewCategory('');
                  }}>{tx("添加分类")}</Button>
                </div>
                <div className="mt-3 text-xs space-y-1">
                  <p className={allocatedPercent > 100 ? 'text-rose-600 dark:text-rose-400' : 'text-zinc-600 dark:text-zinc-300'}>
                    {tx("已分配比例")} <span data-testid="budget-allocated-percent">{allocatedPercent.toFixed(2)}%</span>
                  </p>
                  <p className="text-zinc-500 dark:text-zinc-400">{tx("已分配金额")} {fmt(allocatedAmount)} · {tx("未分配金额")} {fmt(Math.max(0, editForm.total_budget - allocatedAmount))}</p>
                  {allocatedPercent > 100 && <p role="alert" className="text-rose-600 dark:text-rose-400">
                    {tx("合计超过 100%，「{p0}」最大可设置为 {p1}%。", { p0: categoryLabel(limitCategory), p1: maximumPercent.toFixed(2) })}
                  </p>}
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >{tx("取消")}</button>
                <Button
                  type="submit"
                  size="sm"
                  disabled={allocatedPercent > 100}
                  loading={saving}
                >{tx("保存配置")}</Button>
              </div>
            </form>
          </div>
        </div>
      )}
      {isEditModalOpen && deleteCategory && (
        <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/40"
          onPointerDown={() => { menuOpeningPress.current = false; }}
          onClickCapture={event => {
            // Lifting the opening long press can produce a click on the new overlay.
            if (menuOpeningPress.current && event.detail > 0) {
              menuOpeningPress.current = false;
              event.preventDefault();
              event.stopPropagation();
            }
          }}
          onClick={event => { if (event.target === event.currentTarget) setDeleteCategory(null); }}>
          <div role="dialog" aria-modal="true" aria-label={tx("删除预算分类")} className="w-full max-w-sm rounded-t-2xl bg-white dark:bg-zinc-900 p-4 space-y-3 border-t border-zinc-200 dark:border-zinc-700 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{categoryIcon(deleteCategory)} {categoryLabel(deleteCategory)}</p>
            <button type="button" onClick={() => removeBudgetCategory(deleteCategory)} className="w-full py-3 rounded-xl text-sm font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/30">{tx("删除分类")}</button>
            <button type="button" onClick={() => setDeleteCategory(null)} className="w-full py-3 rounded-xl text-sm font-medium text-zinc-600 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-800">{tx("取消")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
