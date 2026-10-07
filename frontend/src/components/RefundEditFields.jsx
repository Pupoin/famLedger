import React from 'react';
import { tx, useLocale } from '../localization';
import { formatDateTime } from '../utils/dates';
import { buildRefundAllocation } from '../utils/refundAllocation';

export default function RefundEditFields({ transaction, candidates, loading, search, onSearch, originalId,
  onOriginalChange, originalAmount, onOriginalAmountChange, refundAmount, onRefundAmountChange,
  currency, onUnlink, unlinking, privacyMode, onAllocate, error, canManage = true,
  recommendationsOnly = true, onRecommendationsChange }) {
  useLocale();
  const info = transaction.transaction_type === 'refund' ? transaction.refund_info : null;
  const selected = candidates.find(row => row.id === originalId);
  const foreign = selected && selected.original_currency !== currency;
  let validation = '';
  if (selected) {
    try { buildRefundAllocation({ ...transaction, original_currency: currency }, selected, originalAmount, refundAmount); }
    catch (err) { validation = tx(err.message); }
  }
  const inputClass = 'mt-1 w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100';
  return <div data-testid="refund-edit-fields" className="space-y-3 p-3 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs">
    <h4 className="font-semibold text-zinc-900 dark:text-zinc-100">{tx('退款冲抵关联 (Refund Allocation)')}</h4>
    {info?.is_linked && <div className="space-y-2">
      <p>{tx('已关联退款随原消费分类；修改分类请编辑原消费。')}</p>
      <p>{tx('原币冲抵额度:')} {privacyMode ? '••••••' : `${info.allocated_amount} ${info.currency}`}</p>
      {info.allocations?.map(row => <div key={row.other_transaction_id} className="p-2 rounded-lg bg-zinc-50 dark:bg-zinc-800">
        <p className="break-words font-medium">{row.narration || row.other_transaction_id}</p>
        <p className="text-zinc-500">{row.account_name} · {formatDateTime(row.occurred_at || row.transacted_at)}</p>
        <p>{tx('原消费冲抵金额')}: {privacyMode ? '••••••' : `${row.allocated_amount} ${row.original_currency}`}</p>
      </div>)}
      <button type="button" disabled={unlinking || !canManage} onClick={onUnlink}
        className="px-3 py-2 rounded-lg border border-rose-300 dark:border-rose-800 text-rose-600 dark:text-rose-400 disabled:opacity-50">{tx('解除与原消费的冲抵关联')}</button>
    </div>}
    {!info?.is_fully_allocated && <>
      <p className="text-zinc-500 dark:text-zinc-400">{tx('推荐退款日前两个月内、相似度大于 0.5 的消费，按相似度排序。')}</p>
      {info?.remaining_amount != null && <p>{tx('剩余未分配')}: {privacyMode ? '••••••' : `${info.remaining_amount} ${info.currency}`}</p>}
      {onRecommendationsChange && <label className="flex items-center gap-2">
        <input type="checkbox" data-testid="search-historical-refund-purchases" checked={!recommendationsOnly} onChange={event => onRecommendationsChange(!event.target.checked)} />
        {tx('搜索全部历史消费（不限两个月及相似度）')}
      </label>}
      {!recommendationsOnly && <label className="block">{tx('搜索原消费')}
        <input type="search" value={search} onChange={event => onSearch(event.target.value)} disabled={unlinking} className={inputClass} />
      </label>}
      <label className="block">{tx('选择原消费')}
        <select value={originalId} onChange={event => onOriginalChange(event.target.value)} disabled={loading || unlinking || !canManage} className={inputClass}>
          <option value="">{tx('保持现有关联／暂不指定')}</option>
          {candidates.map(row => <option key={row.id} value={row.id}>
            {row.narration} · {tx('相似度')} {Math.round(Number(row.similarity_score || 0) * 100)}% · {row.account_name} · {formatDateTime(row.occurred_at || row.transacted_at)} · {privacyMode ? '••••••' : `${row.remaining_refundable} ${row.original_currency || row.currency}`}
          </option>)}
        </select>
      </label>
      {loading && <p>{tx('正在检索候选支出...')}</p>}
      {error && <p role="alert" className="text-rose-600 dark:text-rose-400">{error}</p>}
      {!loading && !error && !candidates.length && <p className="text-zinc-500">{tx('暂无符合条件的消费，可勾选搜索全部历史消费。')}</p>}
      {selected && <>
        <p className="break-words text-zinc-600 dark:text-zinc-300">{selected.narration} · {tx('相似度')} {Math.round(Number(selected.similarity_score || 0) * 100)}% · {tx('剩余可冲抵:')} {privacyMode ? '••••••' : `${selected.remaining_refundable} ${selected.original_currency}`}</p>
        <label className="block">{tx('原消费冲抵金额')} ({selected.original_currency})
          <input type="number" min="0.0001" max={selected.remaining_refundable} step="0.0001" required={foreign} value={originalAmount}
            disabled={unlinking || !canManage} placeholder={foreign ? '' : tx('留空按双方剩余额度冲抵')}
            onChange={event => onOriginalAmountChange(event.target.value)} className={inputClass} />
        </label>
        {foreign && <label className="block">{tx('使用退款原币金额')} ({currency})
          <input type="number" min="0.0001" max={info?.remaining_amount ?? transaction.original_amount} step="0.0001" required value={refundAmount} disabled={unlinking || !canManage}
            onChange={event => onRefundAmountChange(event.target.value)} className={inputClass} />
        </label>}
        {validation && <p role="alert" className="text-rose-600 dark:text-rose-400">{validation}</p>}
        {onAllocate ? <button type="button" data-testid="confirm-refund-allocation"
          disabled={loading || unlinking || !canManage || Boolean(validation)} onClick={onAllocate}
          className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 font-semibold disabled:opacity-40">{unlinking ? tx('保存中...') : tx('确认冲抵')}</button>
          : <p className="text-zinc-500 dark:text-zinc-400">{tx('保存交易时同时提交退款匹配与冲抵额度。')}</p>}
      </>}
    </>}
    {!canManage && <p className="text-zinc-500">{tx('此交易只读，不能修改退款分配。')}</p>}
  </div>;
}
