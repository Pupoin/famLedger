import { categoryLabel, tx, useLocale } from "../localization.js";
import React, { useState, useEffect } from 'react';
import { X, Plus, Trash2, Scissors, Check, AlertCircle, ArrowDown } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';
import { currencySymbol } from '../utils/currency';
import { apiErrorMessage } from '../api/errorMessages';
import { initialTransactionSplits, transactionSplitSummary, buildTransactionSplits, splitMoney } from '../utils/transactionSplits';

export default function SplitTransactionModal({
  isOpen,
  onClose,
  transaction,
  categories = [],
  onSuccess,
}) {
  useLocale();
  const { showToast } = useToast();
  const symbol = currencySymbol(transaction?.currency);

  const [splits, setSplits] = useState(() => initialTransactionSplits(transaction, categories));
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen && transaction) setSplits(initialTransactionSplits(transaction, categories));
    // Loading categories or changing the language must not discard edited rows.
  }, [isOpen, transaction?.id]);

  if (!isOpen || !transaction) return null;
  const summary = transactionSplitSummary(transaction, splits);
  const totalAmount = splitMoney(summary.total);
  const remainingAmount = splitMoney(summary.remaining);
  const isBalanced = summary.balanced;

  const handleAddSplit = () => {
    setSplits(prev => [...prev, {
      id: `split-${Date.now()}-${prev.length}`, category_id: categories[0]?.id || '',
      amount: summary.remaining > 0n ? splitMoney(summary.remaining) : '0.00', notes: '',
    }]);
  };

  const handleRemoveSplit = (idx) => {
    if (splits.length <= 2) {
      showToast(tx("拆分必须包含至少两个子项"), 'warning');
      return;
    }
    setSplits((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleUpdateSplit = (idx, field, value) => {
    setSplits((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
  };

  const handleAutoFillRemaining = (idx) => {
    const others = splits.filter((_, index) => index !== idx);
    const amount = transactionSplitSummary(transaction, others).remaining;
    handleUpdateSplit(idx, 'amount', splitMoney(amount > 0n ? amount : 0n));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    let payload;
    try { payload = buildTransactionSplits(transaction, splits); }
    catch (error) { showToast(tx(error.message), 'error'); return; }

    try {
      setSubmitting(true);
      const res = await fetchWithAuth(`/api/v1/transactions/${transaction.id}/split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        showToast(tx("交易拆分成功！"), 'success');
        if (onSuccess) onSuccess();
        onClose();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(apiErrorMessage(err.detail, '拆分保存失败')), 'error');
      }
    } catch (err) {
      console.error('Error saving transaction splits', err);
      showToast(tx("网络请求错误，请稍后重试"), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleClearSplits = async () => {
    setSubmitting(true);
    try {
      const response = await fetchWithAuth(`/api/v1/transactions/${transaction.id}/split`, { method: 'DELETE' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(tx(apiErrorMessage(data.detail, '解除拆分失败')), 'error');
        return;
      }
      showToast(tx('已解除拆分'), 'success');
      onSuccess?.();
      onClose();
    } catch { showToast(tx('网络请求失败'), 'error'); }
    finally { setSubmitting(false); }
  };

  return (
    <div className="fixed inset-0 z-[80] overflow-y-auto overscroll-contain flex items-center justify-center p-3 sm:p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={() => !submitting && onClose()} />
      <div role="dialog" aria-modal="true" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); if (!submitting) onClose(); } }} className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-lg max-h-[90dvh] overflow-y-auto overscroll-contain border border-zinc-200 dark:border-zinc-800 z-10 animate-in fade-in zoom-in-95 duration-150">
        {/* 头部 */}
        <div className="px-5 py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-300 flex items-center justify-center">
              <Scissors className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                {transaction?.transaction_type === 'refund' ? tx("拆分退款 (Split Refund)") : tx("拆分账单 (Split Transaction)")}
              </h3>
              <p className="text-[11px] text-zinc-500">
                {transaction?.transaction_type === 'refund'
                  ? tx("将单笔退款拆分为多个独立冲抵分类与备注子项")
                  : tx("将单笔交易拆分为多个独立分类与备注子项")}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => !submitting && onClose()}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4 text-xs">
          {/* 原始金额与配平状态指示条 */}
          <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200/80 dark:border-zinc-700/80 flex items-center justify-between">
            <div>
                <span className="text-[11px] text-zinc-400 block">{tx("账户入账金额 (")} {transaction.currency})</span>
              <span className="font-mono text-sm font-bold text-zinc-900 dark:text-white">
                {symbol}{totalAmount}
              </span>
            </div>

            <div className="text-right">
              <span className="text-[11px] text-zinc-400 block">{tx("未分配金额")}</span>
              <span
                className={`font-mono text-sm font-bold ${
                  isBalanced
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-rose-600 dark:text-rose-400'
                }`}
              >
                {symbol}{remainingAmount}
              </span>
            </div>
          </div>

          {/* 子项列表 */}
          <div className="space-y-2.5 max-h-[320px] overflow-y-auto pr-1">
            {splits.map((s, idx) => (
              <div
                key={s.id || idx}
                className="p-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 space-y-2 relative group shadow-2xs"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400 flex items-center gap-1">
                    <span>{tx("子项 #")} {idx + 1}</span>
                  </span>
                  <div className="flex items-center gap-2">
                    {summary.remaining !== 0n && (
                      <button
                        type="button"
                        onClick={() => handleAutoFillRemaining(idx)}
                        className="text-[10.5px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-0.5 cursor-pointer"
                      >
                        <ArrowDown className="w-2.5 h-2.5" />
                        <span>{tx("填充剩余")}</span>
                      </button>
                    )}
                    {splits.length > 2 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveSplit(idx)}
                        className="text-zinc-400 hover:text-rose-600 p-0.5 rounded cursor-pointer"
                        title={tx("删除子项")}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {/* 分类 */}
                  <div>
                    <label className="block text-[10.5px] text-zinc-400 mb-0.5">{tx("分类")}</label>
                    <select
                      value={s.category_id}
                      onChange={(e) => handleUpdateSplit(idx, 'category_id', e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs outline-none focus:ring-1 focus:ring-zinc-900"
                    >
                      <option value="">{tx("未指定 (继承)")}</option>
                      {categories.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.icon || '📦'} {categoryLabel(c.name)}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* 金额 */}
                  <div>
                    <label className="block text-[10.5px] text-zinc-400 mb-0.5">{tx("入账金额 (")} {transaction.currency})</label>
                    <input
                      type="number"
                      min="0.0001"
                      step="0.0001"
                      required
                      value={s.amount}
                      onChange={(e) => handleUpdateSplit(idx, 'amount', e.target.value)}
                      className="w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs font-mono font-medium outline-none focus:ring-1 focus:ring-zinc-900"
                    />
                  </div>
                </div>

                {/* 备注 */}
                <div>
                  <input
                    type="text"
                    placeholder={tx("备注说明 (如：其中餐饮部分)")}
                    value={s.notes}
                    onChange={(e) => handleUpdateSplit(idx, 'notes', e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs outline-none focus:ring-1 focus:ring-zinc-900 placeholder:text-zinc-400"
                  />
                </div>
              </div>
            ))}
          </div>

          {/* 添加子项按钮 */}
          <button
            type="button"
            onClick={handleAddSplit}
            className="w-full py-2 border border-dashed border-zinc-300 dark:border-zinc-700 rounded-xl text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:border-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 flex items-center justify-center gap-1.5 transition cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{tx("添加拆分子项")}</span>
          </button>

          {/* 底部按钮 */}
          <div className="pt-2 flex items-center justify-between border-t border-zinc-100 dark:border-zinc-800">
            <div className="text-[11px]">
              {isBalanced ? (
                <span className="text-emerald-600 dark:text-emerald-400 flex items-center gap-1 font-medium">
                  <Check className="w-3.5 h-3.5" />
                  <span>{tx("金额已精确配平")}</span>
                </span>
              ) : (
                <span className="text-rose-500 dark:text-rose-400 flex items-center gap-1 font-medium">
                  <AlertCircle className="w-3.5 h-3.5" />
                  <span>{tx("需配平至")} {symbol}0.00 {transaction.currency} {tx("方可保存")}</span>
                </span>
              )}
            </div>

            <div className="flex flex-wrap justify-end gap-2">
              {transaction.is_split && <button type="button" onClick={handleClearSplits} disabled={submitting}
                className="px-3 py-1.5 rounded-lg border border-rose-200 dark:border-rose-800 text-rose-600 dark:text-rose-400 disabled:opacity-50">{tx('解除拆分')}</button>}

              <button
                type="button"
                onClick={() => !submitting && onClose()}
                className="px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium cursor-pointer"
              >{tx("取消")}</button>
              <button
                type="submit"
                disabled={submitting || !isBalanced}
                className="px-4 py-1.5 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-100 text-xs font-semibold shadow-xs disabled:opacity-50 cursor-pointer"
              >
                {submitting ? tx("保存中...") : tx("确认拆分")}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
