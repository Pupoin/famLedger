import React, { useState, useEffect } from 'react';
import {
  X,
  RotateCcw,
  Check,
  CreditCard,
  Building2,
  Tag,
  Calendar,
  Layers,
  CircleDollarSign,
  Undo2,
  SlidersHorizontal,
} from 'lucide-react';

export default function TransactionFilterModal({
  isOpen,
  onClose,
  currentFilters = {},
  onApply,
  onReset,
  accounts = [],
  filterOptions = null,
}) {
  // Local draft state initialized from currentFilters
  const [draft, setDraft] = useState({
    account_id: currentFilters?.account_id || '',
    account_mask: currentFilters?.account_mask || '',
    institution_name: currentFilters?.institution_name || '',
    transaction_type: currentFilters?.transaction_type || '',
    category_name: currentFilters?.category_name || '',
    is_refund: Boolean(currentFilters?.is_refund),
    has_refund: Boolean(currentFilters?.has_refund),
    tag: currentFilters?.tag || '',
    min_amount: currentFilters?.min_amount || '',
    max_amount: currentFilters?.max_amount || '',
    start_date: currentFilters?.start_date || '',
    end_date: currentFilters?.end_date || '',
  });

  const [customTagInput, setCustomTagInput] = useState('');

  useEffect(() => {
    if (isOpen) {
      setDraft({
        account_id: currentFilters?.account_id || '',
        account_mask: currentFilters?.account_mask || '',
        institution_name: currentFilters?.institution_name || '',
        transaction_type: currentFilters?.transaction_type || '',
        category_name: currentFilters?.category_name || '',
        is_refund: Boolean(currentFilters?.is_refund),
        has_refund: Boolean(currentFilters?.has_refund),
        tag: currentFilters?.tag || '',
        min_amount: currentFilters?.min_amount || '',
        max_amount: currentFilters?.max_amount || '',
        start_date: currentFilters?.start_date || '',
        end_date: currentFilters?.end_date || '',
      });
    }
  }, [isOpen, currentFilters]);

  // Extract institutions and unique masks from accounts
  const institutions = filterOptions?.institutions?.length
    ? filterOptions.institutions
    : Array.from(new Set(accounts.map((a) => a.institution_name || '招商银行'))).filter(Boolean);

  const categories = filterOptions?.categories || [
    { name: '餐饮美食', icon: '🍴' },
    { name: '超市便利', icon: '🛒' },
    { name: '生活缴费', icon: '⚡' },
    { name: '交通出行', icon: '🚗' },
    { name: '购物消费', icon: '🛍️' },
    { name: '个人/转账', icon: '👤' },
    { name: '其他', icon: '🍪' },
  ];

  const availableTags = filterOptions?.tags || [];

  // Helper date presets
  const applyDatePreset = (preset) => {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const todayStr = `${yyyy}-${mm}-${dd}`;

    if (preset === 'MTD') {
      setDraft((prev) => ({
        ...prev,
        start_date: `${yyyy}-${mm}-01`,
        end_date: todayStr,
      }));
    } else if (preset === '30D') {
      const d = new Date(today);
      d.setDate(d.getDate() - 30);
      const startStr = d.toISOString().slice(0, 10);
      setDraft((prev) => ({
        ...prev,
        start_date: startStr,
        end_date: todayStr,
      }));
    } else if (preset === 'YTD') {
      setDraft((prev) => ({
        ...prev,
        start_date: `${yyyy}-01-01`,
        end_date: todayStr,
      }));
    } else if (preset === 'ALL') {
      setDraft((prev) => ({
        ...prev,
        start_date: '',
        end_date: '',
      }));
    }
  };

  const handleApply = () => {
    onApply(draft);
    onClose();
  };

  const handleResetDraft = () => {
    const emptyFilters = {
      account_id: '',
      account_mask: '',
      institution_name: '',
      transaction_type: '',
      category_name: '',
      is_refund: false,
      has_refund: false,
      tag: '',
      min_amount: '',
      max_amount: '',
      start_date: '',
      end_date: '',
    };
    setDraft(emptyFilters);
    onReset();
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="relative w-full max-w-2xl bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-100 dark:border-zinc-800">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
              <SlidersHorizontal className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                多维交易高级筛选
              </h2>
              <p className="text-xs text-zinc-400">
                支持卡号、金融机构、消费类型、分类、退款与标签全维过滤
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable Filter Form Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-6 custom-scrollbar text-xs">
          {/* ── 1. 金融机构与卡号 ── */}
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <Building2 className="w-3.5 h-3.5 text-blue-500" />
              <span>金融机构 (Institution)</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => setDraft((p) => ({ ...p, institution_name: '' }))}
                className={`px-3 py-1.5 rounded-xl border font-medium transition-all ${
                  !draft.institution_name
                    ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent shadow-xs font-semibold'
                    : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/60'
                }`}
              >
                全部机构
              </button>
              {institutions.map((inst) => {
                const isSelected = draft.institution_name === inst;
                return (
                  <button
                    key={inst}
                    type="button"
                    onClick={() =>
                      setDraft((p) => ({
                        ...p,
                        institution_name: isSelected ? '' : inst,
                      }))
                    }
                    className={`px-3 py-1.5 rounded-xl border font-medium transition-all ${
                      isSelected
                        ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent shadow-xs font-semibold'
                        : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/60'
                    }`}
                  >
                    {inst}
                  </button>
                );
              })}
            </div>

            {/* 账户 / 卡号 (Card Mask) */}
            <div className="pt-1 space-y-2">
              <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
                <CreditCard className="w-3.5 h-3.5 text-purple-500" />
                <span>卡号与账户 (Card / Account)</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setDraft((p) => ({ ...p, account_id: '', account_mask: '' }))
                  }
                  className={`p-2.5 rounded-xl border text-left transition-all ${
                    !draft.account_id && !draft.account_mask
                      ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent font-semibold shadow-xs'
                      : 'bg-white dark:bg-zinc-850 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                  }`}
                >
                  <span className="font-semibold block">全部卡号与账户</span>
                  <span className="text-[11px] opacity-70">不限卡号</span>
                </button>

                {accounts.map((acc) => {
                  const m = acc.name.match(/\(([0-9Xx]{4})\)/);
                  const mask = m ? m[1] : acc.mask || acc.name.slice(-4);
                  const isSelected =
                    draft.account_id === acc.id || draft.account_mask === mask;

                  return (
                    <button
                      key={acc.id}
                      type="button"
                      onClick={() =>
                        setDraft((p) => ({
                          ...p,
                          account_id: isSelected ? '' : acc.id,
                          account_mask: isSelected ? '' : mask,
                        }))
                      }
                      className={`p-2.5 rounded-xl border text-left transition-all ${
                        isSelected
                          ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent font-semibold shadow-xs'
                          : 'bg-white dark:bg-zinc-850 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold truncate max-w-[170px]">{acc.name}</span>
                        <span className="font-mono text-[11px] px-1.5 py-0.5 rounded-md bg-zinc-200/60 dark:bg-zinc-700/60 shrink-0">
                          *{mask}
                        </span>
                      </div>
                      <span className="text-[11px] opacity-70 block mt-0.5">
                        {acc.institution_name || '招商银行'} · {acc.account_type || '借记卡'}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          {/* ── 2. 消费与交易类型 ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <Layers className="w-3.5 h-3.5 text-emerald-500" />
              <span>交易类型 (Transaction Type)</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {[
                { value: '', label: '全部类型' },
                { value: 'expense', label: '💸 支出 (Expense)' },
                { value: 'income', label: '💰 收入 (Income)' },
                { value: 'transfer', label: '🔄 内部转账 (Transfer)' },
                { value: 'refund', label: '↩️ 退款冲抵 (Refund)' },
              ].map((t) => {
                const isSelected = draft.transaction_type === t.value;
                return (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() =>
                      setDraft((p) => ({
                        ...p,
                        transaction_type: isSelected ? '' : t.value,
                      }))
                    }
                    className={`px-3 py-1.5 rounded-xl border font-medium transition-all ${
                      isSelected
                        ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent shadow-xs font-semibold'
                        : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/60'
                    }`}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── 3. 消费分类 (Category) ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <Tag className="w-3.5 h-3.5 text-amber-500" />
              <span>智能分类 (Category)</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => setDraft((p) => ({ ...p, category_name: '' }))}
                className={`px-3 py-1.5 rounded-xl border font-medium transition-all ${
                  !draft.category_name
                    ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent shadow-xs font-semibold'
                    : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/60'
                }`}
              >
                全部分类
              </button>
              {categories.map((cat) => {
                const isSelected = draft.category_name === cat.name;
                return (
                  <button
                    key={cat.name}
                    type="button"
                    onClick={() =>
                      setDraft((p) => ({
                        ...p,
                        category_name: isSelected ? '' : cat.name,
                      }))
                    }
                    className={`px-3 py-1.5 rounded-xl border font-medium transition-all flex items-center gap-1.5 ${
                      isSelected
                        ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent shadow-xs font-semibold'
                        : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/60'
                    }`}
                  >
                    <span>{cat.icon || '📦'}</span>
                    <span>{cat.name}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── 4. 退款专属筛选 (Refund Filter) ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <Undo2 className="w-3.5 h-3.5 text-teal-500" />
              <span>退款与冲抵筛选 (Refund & Offset)</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() =>
                  setDraft((p) => ({ ...p, is_refund: !p.is_refund }))
                }
                className={`p-3 rounded-xl border text-left flex items-center justify-between transition-all ${
                  draft.is_refund
                    ? 'bg-teal-50 dark:bg-teal-950/40 border-teal-500 text-teal-900 dark:text-teal-200 font-semibold'
                    : 'bg-white dark:bg-zinc-850 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300'
                }`}
              >
                <div>
                  <span className="block font-semibold">仅看退款交易</span>
                  <span className="text-[11px] text-zinc-400">退款到账入账记录</span>
                </div>
                {draft.is_refund && <Check className="w-4 h-4 text-teal-600" />}
              </button>

              <button
                type="button"
                onClick={() =>
                  setDraft((p) => ({ ...p, has_refund: !p.has_refund }))
                }
                className={`p-3 rounded-xl border text-left flex items-center justify-between transition-all ${
                  draft.has_refund
                    ? 'bg-teal-50 dark:bg-teal-950/40 border-teal-500 text-teal-900 dark:text-teal-200 font-semibold'
                    : 'bg-white dark:bg-zinc-850 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300'
                }`}
              >
                <div>
                  <span className="block font-semibold">仅看被退款冲抵的原消费</span>
                  <span className="text-[11px] text-zinc-400">已发生冲抵的支出流水</span>
                </div>
                {draft.has_refund && <Check className="w-4 h-4 text-teal-600" />}
              </button>
            </div>
          </div>

          {/* ── 5. 标签筛选 (Tags) ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <Tag className="w-3.5 h-3.5 text-rose-500" />
              <span>交易标签 (Tags)</span>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {availableTags.length > 0 &&
                availableTags.map((tg) => {
                  const isSelected = draft.tag === tg;
                  return (
                    <button
                      key={tg}
                      type="button"
                      onClick={() =>
                        setDraft((p) => ({
                          ...p,
                          tag: isSelected ? '' : tg,
                        }))
                      }
                      className={`px-3 py-1.5 rounded-xl border font-medium transition-all ${
                        isSelected
                          ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent font-semibold shadow-xs'
                          : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300'
                      }`}
                    >
                      #{tg}
                    </button>
                  );
                })}

              {/* Custom tag input */}
              <div className="inline-flex items-center gap-1.5">
                <input
                  type="text"
                  placeholder="输入自定义标签过滤..."
                  value={draft.tag || customTagInput}
                  onChange={(e) => {
                    const val = e.target.value;
                    setCustomTagInput(val);
                    setDraft((p) => ({ ...p, tag: val }));
                  }}
                  className="px-3 py-1.5 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-hidden focus:ring-1 focus:ring-zinc-400 w-48"
                />
                {draft.tag && (
                  <button
                    type="button"
                    onClick={() => {
                      setDraft((p) => ({ ...p, tag: '' }));
                      setCustomTagInput('');
                    }}
                    className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 p-1"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* ── 6. 金额范围 (Amount Range) ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <CircleDollarSign className="w-3.5 h-3.5 text-indigo-500" />
              <span>金额范围 (Amount Range)</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="relative flex-1">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 font-mono">¥</span>
                <input
                  type="number"
                  placeholder="最小金额"
                  value={draft.min_amount}
                  onChange={(e) => setDraft((p) => ({ ...p, min_amount: e.target.value }))}
                  className="w-full pl-7 pr-3 py-2 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl font-mono text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-hidden focus:ring-1 focus:ring-zinc-400"
                />
              </div>
              <span className="text-zinc-400 font-semibold">至</span>
              <div className="relative flex-1">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400 font-mono">¥</span>
                <input
                  type="number"
                  placeholder="最大金额"
                  value={draft.max_amount}
                  onChange={(e) => setDraft((p) => ({ ...p, max_amount: e.target.value }))}
                  className="w-full pl-7 pr-3 py-2 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl font-mono text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-hidden focus:ring-1 focus:ring-zinc-400"
                />
              </div>
            </div>
          </div>

          {/* ── 7. 日期范围与快捷预设 (Date Range) ── */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-zinc-800 dark:text-zinc-200 font-semibold">
              <Calendar className="w-3.5 h-3.5 text-sky-500" />
              <span>交易日期 (Date Range)</span>
            </div>
            {/* Quick presets */}
            <div className="flex items-center gap-2 flex-wrap">
              {[
                { label: '全部日期', key: 'ALL' },
                { label: '本月 (MTD)', key: 'MTD' },
                { label: '最近 30 天', key: '30D' },
                { label: '本年 (YTD)', key: 'YTD' },
              ].map((ps) => (
                <button
                  key={ps.key}
                  type="button"
                  onClick={() => applyDatePreset(ps.key)}
                  className="px-2.5 py-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-[11px] font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700"
                >
                  {ps.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-3 pt-1">
              <input
                type="date"
                value={draft.start_date}
                onChange={(e) => setDraft((p) => ({ ...p, start_date: e.target.value }))}
                className="flex-1 px-3 py-2 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl font-mono text-zinc-900 dark:text-zinc-100 focus:outline-hidden focus:ring-1 focus:ring-zinc-400"
              />
              <span className="text-zinc-400 font-semibold">至</span>
              <input
                type="date"
                value={draft.end_date}
                onChange={(e) => setDraft((p) => ({ ...p, end_date: e.target.value }))}
                className="flex-1 px-3 py-2 bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200 dark:border-zinc-700 rounded-xl font-mono text-zinc-900 dark:text-zinc-100 focus:outline-hidden focus:ring-1 focus:ring-zinc-400"
              />
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between px-5 py-3.5 border-t border-zinc-100 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50">
          <button
            type="button"
            onClick={handleResetDraft}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>重置所有筛选</span>
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleApply}
              className="inline-flex items-center gap-1.5 px-5 py-2 text-xs font-bold rounded-xl bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100 text-white shadow-xs transition-colors active:scale-95"
            >
              <Check className="w-3.5 h-3.5" />
              <span>应用筛选条件</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
