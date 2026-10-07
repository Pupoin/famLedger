import React, { useEffect, useRef } from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import { tx, useLocale } from '../localization';
import { currencySymbol, formatCurrency, originalTransactionMoney } from '../utils/currency';
import { formatDateTime } from '../utils/dates';

function TransactionSummary({ transaction, privacyMode, label }) {
  const money = originalTransactionMoney(transaction);
  return (
    <div className="p-3 bg-zinc-50 dark:bg-zinc-800/40 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs space-y-1.5 min-w-0">
      <p className="font-semibold text-zinc-900 dark:text-zinc-100">{label}</p>
      <p className="break-words">{transaction.account_name || tx('私有账户')}</p>
      <p className="break-words">{transaction.name || transaction.narration}</p>
      <p className="font-mono font-semibold">{privacyMode ? '••••••' : money.amount == null
        ? tx('无权查看配对交易详情') : `${formatCurrency(money.amount, currencySymbol(money.currency))} ${money.currency}`}</p>
      {(transaction.occurred_at || transaction.transacted_at) && <p className="text-zinc-500 dark:text-zinc-400">{formatDateTime(transaction.occurred_at || transaction.transacted_at)}</p>}
    </div>
  );
}

export default function DeleteTransactionModal({ transaction, scope, onScopeChange, onConfirm, onClose, deleting, privacyMode }) {
  useLocale();
  const cancelRef = useRef(null);
  useEffect(() => { cancelRef.current?.focus(); }, []);
  if (!transaction) return null;
  const info = transaction.deletion_info;
  const paired = Boolean(info?.transfer_id || transaction.paired_transfer);
  const counterpart = transaction.paired_transfer?.counterpart;
  const canDeletePair = info?.can_delete_pair === true;
  const validChoice = !paired || scope === 'single' || (scope === 'pair' && canDeletePair);
  const canDelete = info?.can_delete !== false;
  return (
    <div className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={() => !deleting && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="delete-transaction-title"
        className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-5 max-w-lg w-full max-h-[90dvh] overflow-y-auto overscroll-contain shadow-2xl space-y-4 text-zinc-700 dark:text-zinc-300"
        onClick={event => event.stopPropagation()} onKeyDown={event => {
          if (event.key === 'Escape') { event.stopPropagation(); if (!deleting) onClose(); }
        }}>
        <div className="flex items-center gap-3">
          <Trash2 className="w-5 h-5 shrink-0 text-rose-600 dark:text-rose-400" />
          <div>
            <h3 id="delete-transaction-title" className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx(paired ? '删除已配对的转账？' : '确认删除该交易？')}</h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx('此操作不可撤销')}</p>
          </div>
        </div>
        <div className={`grid gap-3 ${paired ? 'sm:grid-cols-2' : ''}`}>
          <TransactionSummary transaction={transaction} privacyMode={privacyMode} label={tx('当前交易')} />
          {paired && counterpart && <TransactionSummary transaction={counterpart} privacyMode={privacyMode} label={tx('配对交易')} />}
        </div>
        {paired && <fieldset disabled={deleting || !canDelete} className="space-y-2">
          <legend className="text-sm font-semibold mb-2">{tx('请选择删除范围')}</legend>
          {[
            { value: 'single', title: '只删除这笔，解除配对', description: '保留另一笔的金额、方向和转账类型。', disabled: false },
            { value: 'pair', title: '同时删除配对的两笔', description: '两侧账户的余额都会重新计算。', disabled: !canDeletePair },
          ].map(option => <label key={option.value} className={`flex gap-3 p-3 border rounded-xl text-sm ${option.disabled
            ? 'border-zinc-200 dark:border-zinc-800 opacity-50' : 'border-zinc-300 dark:border-zinc-700 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800'}`}>
            <input type="radio" name="transaction-delete-scope" value={option.value} checked={scope === option.value}
              disabled={option.disabled} onChange={() => onScopeChange(option.value)} className="mt-1 accent-rose-600" />
            <span><span className="block font-semibold">{tx(option.title)}</span><span className="block text-xs text-zinc-500 dark:text-zinc-400 mt-1">{tx(option.description)}</span></span>
          </label>)}
          {info?.pair_reason && <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx(info.pair_reason)}</p>}
        </fieldset>}
        {info?.linked_refund_count > 0 && <p role="note" className="text-xs text-amber-700 dark:text-amber-400">{tx('这笔消费关联了 {p0} 笔退款。删除后解除冲抵关联，退款流水会保留。', { p0: info.linked_refund_count })}</p>}
        {info?.has_refund_links && <p role="note" className="text-xs text-amber-700 dark:text-amber-400">{tx('删除这笔退款后解除冲抵关联，原消费流水会保留。')}</p>}
        {!canDelete && info?.reason && <p role="alert" className="text-xs text-rose-600 dark:text-rose-400">{tx(info.reason)}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <button ref={cancelRef} type="button" disabled={deleting} onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-semibold hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50">{tx('取消')}</button>
          <button type="button" data-testid="confirm-delete-transaction-btn" disabled={deleting || !validChoice || !canDelete}
            onClick={() => onConfirm(paired ? scope : 'single')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 disabled:opacity-50 disabled:cursor-not-allowed">
            {deleting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {tx(deleting ? '正在删除...' : '确认删除')}
          </button>
        </div>
      </div>
    </div>
  );
}
