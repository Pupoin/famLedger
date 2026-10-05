import React from 'react';
import { tx, categoryLabel } from '../localization';

export default function RuleActionValue({ action, onChange, categories }) {
  const className = 'w-full min-w-0 px-2.5 py-1.5 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg outline-none text-xs';
  if (action.type === 'set_category') return <select required aria-label={tx('选择分类')} className={className} value={action.value ?? ''} onChange={event => onChange({ value: event.target.value })}>
    <option value="">{tx('选择分类')}</option>{categories.map(category => <option key={category.id} value={category.id}>{category.icon} {categoryLabel(category.name)}</option>)}
  </select>;
  if (action.type === 'exclude_from_statistics') return <select aria-label={tx('不计入统计')} className={className} value={String(action.value)} onChange={event => onChange({ value: event.target.value === 'true' })}>
    <option value="true">{tx('不计入统计')}</option><option value="false">{tx('计入统计')}</option>
  </select>;
  if (action.type === 'set_transaction_type') return <select required className={className} value={action.value ?? ''} onChange={event => onChange({ value: event.target.value })}>
    <option value="">{tx('选择交易类型')}</option>{[['expense', '支出'], ['income', '收入'], ['refund', '退款'], ['transfer', '转账']].map(([value, label]) => <option key={value} value={value}>{tx(label)}</option>)}
  </select>;
  return <div className="w-full space-y-1">
    <input type="text" aria-label={tx('动作值')} value={action.value ?? ''} onChange={event => onChange({ value: event.target.value })} required={action.type !== 'set_note'} className={className} />
    {action.type === 'set_note' && <select aria-label={tx('备注写入模式')} className={className} value={action.mode || 'overwrite'} onChange={event => onChange({ mode: event.target.value })}>
      <option value="overwrite">{tx('覆盖备注')}</option><option value="append">{tx('追加备注')}</option><option value="prepend">{tx('前置备注')}</option>
    </select>}
  </div>;
}
