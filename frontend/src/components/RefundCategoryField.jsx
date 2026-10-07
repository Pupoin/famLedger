import React from 'react';
import { categoryLabel, tx } from '../localization';

export function transactionCategoryLabel(transaction) {
  const refund = transaction?.refund_info || transaction?.refund_category_info;
  return transaction?.transaction_type === 'refund' && refund?.category_editable === false
    ? refund.linked_categories?.map(c => categoryLabel(c.name)).join(' / ') || tx('随原消费分类')
    : categoryLabel(transaction?.category_name);
}

export default function RefundCategoryField({ transaction, categories, value, transactionType, onChange }) {
  if (transactionType === 'transfer') return null;
  const refund = transactionType === 'refund' && transaction.transaction_type === 'refund' ? transaction.refund_info : null;
  const locked = refund?.category_editable === false;
  const linked = refund?.linked_categories || [];
  return (
    <div className="space-y-1">
      <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">
        {tx(locked ? '退款分类（随原消费）' : refund?.is_linked ? '未关联部分的分类' : '交易分类 (单选)')}
      </label>
      {locked ? (
        <div data-testid="refund-category-readonly" className="text-xs text-zinc-900 dark:text-zinc-100 space-y-1">
          <p>{linked.map(c => `${c.icon || '📦'} ${categoryLabel(c.name)}`).join(' / ') || tx('随原消费分类')}</p>
          <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{tx('已关联退款随原消费分类；修改分类请编辑原消费。')}</p>
        </div>
      ) : (
        <>
          <select data-testid="edit-category-select" value={value} onChange={e => onChange(e.target.value)}
            className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500">
            <option value="">{tx('其他')}</option>
            {categories.filter(c => c.name === '其他' || !c.category_type || c.category_type === (transactionType === 'refund' ? 'expense' : transactionType))
              .map(c => <option key={c.id} value={c.id}>{c.icon} {categoryLabel(c.name)}</option>)}
          </select>
          {refund?.is_linked && (
            <div data-testid="refund-linked-categories" className="text-[11px] text-zinc-500 dark:text-zinc-400">
              <p>{tx('已关联部分分类')}: {linked.map(c => `${c.icon || '📦'} ${categoryLabel(c.name)}`).join(' / ') || tx('随原消费分类')}</p>
              <p>{tx('此设置只影响未关联的剩余退款，不改变原消费或已关联部分。')}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
