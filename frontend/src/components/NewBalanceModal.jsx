import { categoryLabel, tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useMemo } from 'react';
import {
  X,
  ShoppingCart,
  CircleDollarSign,
  ArrowLeftRight,
  SlidersHorizontal,
} from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { currencySymbol } from '../utils/currency';
import { useToast } from '../ToastContext';
import { toLocalISODate, toLocalISOTime, localToUTCISO } from '../utils/dates';
import { formatAccountWithEmoji } from '../utils/accountIcons';
import { isLiabilityAccount, normalizeAccountTypeKey } from '../utils/accountTypes';

export default function NewBalanceModal({
  isOpen,
  onClose,
  account,
  onSuccess,
}) {
  useLocale();
  const nativeSymbol = currencySymbol(account?.currency);
  const { showToast } = useToast();

  const [date, setDate] = useState(() => toLocalISODate(new Date()));
  const [time, setTime] = useState(() => toLocalISOTime(new Date(), true));
  const [newBalance, setNewBalance] = useState('');
  const [reason, setReason] = useState('expense'); // 'expense' | 'income' | 'transfer' | 'adjustment'
  const [txnName, setTxnName] = useState('');
  const [categoryId, setCategoryId] = useState('');
  const [counterpartyId, setCounterpartyId] = useState('');
  const [allAccounts, setAllAccounts] = useState([]);
  const [allCategories, setAllCategories] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (account && isOpen) {
      const now = new Date();
      setNewBalance(parseFloat(account.balance || 0).toFixed(2));
      setDate(toLocalISODate(now));
      setTime(toLocalISOTime(now, true));
      setReason('expense');
      setTxnName('');
      setCategoryId('');

      // 动态拉取当前家庭真实的分类体系，支持未分类与自适应筛选
      fetchWithAuth('/api/v1/categories')
        .then((res) => res.json())
        .then((data) => {
          const cats = data.categories || data.items || [];
          setAllCategories(cats);
        })
        .catch(() => {});

      // Fetch accounts for counterparty transfer
      fetchWithAuth('/api/v1/accounts')
        .then((res) => res.json())
        .then((data) => {
          const accs = data.accounts || data.items || [];
          setAllAccounts(accs.filter((a) => a.id !== account.id));
          if (accs.length > 0) {
            const other = accs.find((a) => a.id !== account.id);
            if (other) setCounterpartyId(other.id);
          }
        })
        .catch(() => {});
    }
  }, [account, isOpen]);

  const filteredCategories = useMemo(() => {
    const targetType = reason === 'income' ? 'income' : 'expense';
    return allCategories.filter((c) => (c.category_type || 'expense') === targetType);
  }, [allCategories, reason]);

  const isLiab = isLiabilityAccount(account);
  const currentBal = parseFloat(account?.balance || 0);
  const targetBal = parseFloat(newBalance || 0);
  const diff = targetBal - currentBal;
  const isDiff = Math.abs(diff) > 0.001;
  const isDecreased = diff < 0;

  // 区分资产账户与负债账户（信用卡/贷款）：
  // 1. 资产账户：diff > 0 资产增加，为收入/转入，禁用“支出”；diff < 0 资产减少，为支出/转出，禁用“收入”
  // 2. 负债账户：diff > 0 欠款增加，为消费/支出，禁用“收入”；diff < 0 欠款减少，为还款/转入，禁用“支出”
  const isExpenseDisabled = isDiff && (isLiab ? diff < 0 : diff > 0);
  const isIncomeDisabled = isDiff && (isLiab ? diff > 0 : diff < 0);

  // 当金额方向改变导致当前选项被禁用时，自动切换至合法的选项
  useEffect(() => {
    if (!isOpen || !account || !isDiff) return;
    if (isLiab) {
      if (diff > 0 && reason === 'income') {
        setReason('expense');
      } else if (diff < 0 && reason === 'expense') {
        setReason('income');
      }
    } else {
      if (diff > 0 && reason === 'expense') {
        setReason('income');
      } else if (diff < 0 && reason === 'income') {
        setReason('expense');
      }
    }
  }, [isOpen, account, diff, isDiff, reason, isLiab]);

  if (!isOpen || !account) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!newBalance && newBalance !== 0) {
      showToast(tx("请输入新余额"), 'error');
      return;
    }

    try {
      setSubmitting(true);
      const res = await fetchWithAuth(`/api/v1/accounts/${account.id}/reconcile-balance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          new_balance: targetBal,
          date: date,
          time: time,
          occurred_at: localToUTCISO(date, time),
          reconciliation_type: isDiff ? reason : 'adjustment',
          name: txnName || undefined,
          category_id: categoryId || undefined,
          counterparty_account_id: counterpartyId || undefined,
        }),
      });

      if (res.ok) {
        if (!isDiff) {
          showToast(tx("账户余额核对一致，已刷新对账基准时间"), 'info');
        } else {
          showToast(tx("新余额已更新并成功生成对账记录！"), 'success');
        }
        if (onSuccess) onSuccess();
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        window.dispatchEvent(new CustomEvent('transaction-added'));
        onClose();
      } else {
        const err = await res.json();
        showToast(tx(err.detail || '更新失败'), 'error');
      }
    } catch (err) {
      showToast(tx("网络请求错误"), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const accountTypeName =
    normalizeAccountTypeKey(account) === 'credit_card'
      ? '信用卡'
      : normalizeAccountTypeKey(account) === 'loan'
      ? '贷款'
      : isLiab
      ? '负债'
      : '借记卡';

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog Card (Exact 14.png) */}
      <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="px-6 pt-5 pb-3 flex items-center justify-between">
          <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("确认新余额")}</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="px-6 pb-6 space-y-4 text-xs sm:text-sm">
          {/* Summary Notice */}
          <div className="text-zinc-600 dark:text-zinc-300 space-y-1">
            <p>{tx("Set")}{' '} <span className="font-semibold text-zinc-900 dark:text-white">{tx(accountTypeName)} {tx("余额")}</span> {tx("在")} {' '}
              <span className="font-semibold text-zinc-900 dark:text-white">{date} {time}</span> {tx("到")} {' '}
              <span className="font-semibold text-zinc-900 dark:text-white">{nativeSymbol}{targetBal.toFixed(2)}</span>.
            </p>
            <p className="text-xs text-zinc-400 dark:text-zinc-500">{tx("所有未来的交易和余额都将根据此更新重新计算。")}</p>
          </div>

          {/* Quick Balance & Date/Time inputs */}
          <div className="space-y-3 p-3 bg-zinc-50 dark:bg-zinc-800/40 rounded-xl border border-zinc-200/60 dark:border-zinc-800">
            <div>
              <label className="block text-[11px] font-medium text-zinc-500 mb-1">{tx("设定新余额 ({p0})", {p0: account.currency})}</label>
              <input
                type="number"
                step="0.01"
                required
                value={newBalance}
                onChange={(e) => setNewBalance(e.target.value)}
                className="w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 font-mono font-bold text-zinc-900 dark:text-white text-sm focus:outline-hidden focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="block text-[11px] font-medium text-zinc-500">{tx("生效详细时间 (时分秒)")}</label>
                <button
                  type="button"
                  onClick={() => {
                    const n = new Date();
                    setDate(toLocalISODate(n));
                    setTime(toLocalISOTime(n, true));
                  }}
                  className="text-[11px] text-zinc-500 hover:text-zinc-900 dark:hover:text-white flex items-center gap-0.5 cursor-pointer"
                  title={tx("设为当前时间")}
                >
                  <span>⏱️</span>
                  <span>{tx("设为此时此刻")}</span>
                </button>
              </div>
              <div className="grid grid-cols-5 gap-2">
                <div className="col-span-3">
                  <input
                    type="date"
                    required
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white text-xs font-mono focus:outline-hidden focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
                  />
                </div>
                <div className="col-span-2">
                  <input
                    type="time"
                    step="1"
                    required
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white text-xs font-mono focus:outline-hidden focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white"
                  />
                </div>
              </div>
              <div className="mt-1 text-[11px] text-zinc-400 font-mono">{tx("生效时刻：")} {date} {time}
              </div>
            </div>
          </div>

          {/* ── Zero-Diff Informative Banner ── */}
          {!isDiff && (
            <div className="p-3.5 rounded-xl bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-800/60 text-xs text-amber-800 dark:text-amber-300 flex items-start gap-2.5">
              <span className="text-base leading-none">ℹ️</span>
              <div className="space-y-0.5">
                <p className="font-bold text-amber-900 dark:text-amber-200">{tx("新余额与当前余额一致（差额 {p0}0.00）", {p0: nativeSymbol})}</p>
                <p className="text-[11px] text-amber-700 dark:text-amber-400 leading-relaxed">{tx("点击确认将仅刷新对账核对时间，")} <strong>{tx("不会在活动流水列表中生成新的收支或对账交易")}</strong> {tx("。若需记录一笔对账流水，请在上方输入不同的实际盘点余额。")}</p>
              </div>
            </div>
          )}

          {/* ── Difference Section (Exact 14.png) ── */}
          {isDiff && (
            <div className="space-y-3 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/80 dark:bg-zinc-800/50 p-4">
              <div>
                <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{tx("这笔余额差额是什么？")}</h3>
                <p className="mt-0.5 text-xs text-zinc-500 font-medium">
                  {isDecreased
                    ? (isLiab ? tx("债务欠款减少了 {p0}{p1}", {p0: nativeSymbol, p1: Math.abs(diff).toFixed(2)}) : tx("余额减少了 {p0}{p1}", {p0: nativeSymbol, p1: Math.abs(diff).toFixed(2)}))
                    : (isLiab ? tx("债务欠款增加了 {p0}{p1}", {p0: nativeSymbol, p1: Math.abs(diff).toFixed(2)}) : tx("余额增加了 {p0}{p1}", {p0: nativeSymbol, p1: Math.abs(diff).toFixed(2)}))}
                </p>
              </div>

              {/* 2x2 Grid Radio Cards (Exact 14.png) */}
              <div className="grid grid-cols-2 gap-2">
                {[
                  { id: 'expense', label: isLiab ? tx("消费/支出") : tx("支出"), icon: ShoppingCart },
                  { id: 'income', label: isLiab ? tx("还款/存入") : tx("收入"), icon: CircleDollarSign },
                  { id: 'transfer', label: '转账', icon: ArrowLeftRight },
                  { id: 'adjustment', label: '仅调整余额', icon: SlidersHorizontal },
                ].map((item) => {
                  const Icon = item.icon;
                  const isSelected = reason === item.id;
                  const isDisabled =
                    (item.id === 'expense' && isExpenseDisabled) ||
                    (item.id === 'income' && isIncomeDisabled);

                  return (
                    <label
                      key={item.id}
                      data-testid={`balance-reason-${item.id}`}
                      onClick={() => {
                        if (!isDisabled) setReason(item.id);
                      }}
                      className={`flex items-center gap-2 px-3 py-2.5 rounded-xl border transition-all ${
                        isDisabled
                          ? 'opacity-40 cursor-not-allowed bg-zinc-100/70 dark:bg-zinc-800/30 border-zinc-200 dark:border-zinc-800 text-zinc-400 dark:text-zinc-600 select-none'
                          : isSelected
                          ? 'border-zinc-900 dark:border-white bg-white dark:bg-zinc-900 shadow-xs cursor-pointer'
                          : 'border-zinc-200 dark:border-zinc-700/80 bg-white/70 dark:bg-zinc-800/60 hover:bg-white dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-300 cursor-pointer'
                      }`}
                      title={
                        isDisabled
                          ? item.id === 'expense'
                            ? (isLiab ? tx("欠款减少不是消费支出，不可选") : tx("余额增加不是支出，不可选"))
                            : (isLiab ? tx("欠款增加不是还款存入，不可选") : tx("余额减少不是收入，不可选"))
                          : ''
                      }
                    >
                      <input
                        type="radio"
                        name="balance_reason"
                        value={item.id}
                        checked={isSelected}
                        disabled={isDisabled}
                        onChange={() => {
                          if (!isDisabled) setReason(item.id);
                        }}
                        className="text-zinc-900 dark:text-white focus:ring-0 cursor-pointer disabled:cursor-not-allowed"
                      />
                      <Icon
                        className={`w-4 h-4 shrink-0 ${
                          isDisabled
                            ? 'text-zinc-400 dark:text-zinc-600'
                            : isSelected
                            ? 'text-zinc-900 dark:text-white'
                            : 'text-zinc-500'
                        }`}
                      />
                      <div className="flex flex-col">
                        <span
                          className={`text-xs font-semibold ${
                            isDisabled
                              ? 'text-zinc-400 dark:text-zinc-600'
                              : isSelected
                              ? 'text-zinc-900 dark:text-white'
                              : 'text-zinc-700 dark:text-zinc-300'
                          }`}
                        >
                          {tx(item.label)}
                        </span>
                        {isDisabled && (
                          <span className="text-[11px] text-zinc-400 dark:text-zinc-600 leading-none">
                            {item.id === 'expense'
                              ? (isLiab ? tx("(欠款增加可选)") : tx("(仅减少可选)"))
                              : (isLiab ? tx("(欠款减少可选)") : tx("(仅增加可选)"))}
                          </span>
                        )}
                      </div>
                    </label>
                  );
                })}
              </div>

              {/* Dynamic sub-fields for expense/income */}
              {(reason === 'expense' || reason === 'income') && (
                <div className="space-y-2.5 pt-1 animate-in fade-in duration-100">
                  <div>
                    <label className="block text-[11px] font-medium text-zinc-500 mb-1">{tx("交易名称 (选填)")}</label>
                    <input
                      type="text"
                      placeholder={reason === 'expense' ? tx("如：余额核对调整支出") : tx("如：余额核对补记收入")}
                      value={txnName}
                      onChange={(e) => setTxnName(e.target.value)}
                      className="w-full px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-white focus:ring-1 focus:ring-zinc-800"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-medium text-zinc-500 mb-1">{tx("选择对应分类")}</label>
                    <select
                      value={categoryId}
                      onChange={(e) => setCategoryId(e.target.value)}
                      className="w-full px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-white focus:ring-1 focus:ring-zinc-800"
                    >
                      <option value="">{tx("未分类 (默认)")}</option>
                      {filteredCategories.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.icon ? `${c.icon} ` : ''}{categoryLabel(c.name)}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              {/* Dynamic sub-field for transfer */}
              {reason === 'transfer' && (
                <div className="pt-1 animate-in fade-in duration-100">
                  <label className="block text-[11px] font-medium text-zinc-500 mb-1">{tx("选择对端转账账户")}</label>
                  <select
                    value={counterpartyId}
                    onChange={(e) => setCounterpartyId(e.target.value)}
                    className="w-full px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-white focus:ring-1 focus:ring-zinc-800"
                  >
                    {allAccounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {formatAccountWithEmoji(a)}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Footnote hint (Exact 14.png) */}
              <p className="text-[11px] text-zinc-400 dark:text-zinc-500 pt-0.5">
                {reason === 'adjustment'
                  ? tx("生成余额调整记录，不计入日常收支统计。")
                  : reason === 'transfer' && !counterpartyId ? tx("未选择对端账户，将记录为外部转账，仅改变此账户余额。") : tx("请选择差额原因。选择支出或收入后，还需要选择对应分类。")}
              </p>
            </div>
          )}

          {/* Submit Button (Exact 14.png full-width black button) */}
          <button
            type="submit"
            disabled={submitting}
            className="w-full py-2.5 px-4 rounded-xl font-bold text-xs sm:text-sm bg-zinc-900 hover:bg-zinc-800 text-white dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100 shadow-sm transition-all active:scale-[0.99] cursor-pointer disabled:opacity-50"
          >
            {submitting ? tx("正在更新...") : tx("确认")}
          </button>
        </form>
      </div>
    </div>
  );
}
