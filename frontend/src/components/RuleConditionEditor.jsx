import React, { useState } from 'react';
import { tx, categoryLabel } from '../localization';

const inputClass = 'w-full min-w-0 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-2 text-xs';
const fields = ['merchant', 'amount', 'account', 'notes', 'category', 'type', 'currency', 'tags', 'status', 'transacted_at', 'is_reimbursable', 'excluded_from_stats', 'import_source', 'bank_action'];
const fieldNames = { merchant: '商户', amount: '金额', account: '账户', notes: '备注', category: '分类', type: '类型', currency: '币种', tags: '标签', status: '状态', transacted_at: '日期', is_reimbursable: '可报销', excluded_from_stats: '不计入统计', import_source: '导入来源', bank_action: '银行交易动作' };
const operations = ['equals', 'not_equals', 'contains', 'not_contains', 'starts_with', 'ends_with', 'regex', '>', '>=', '<', '<=', 'in', 'not_in', 'between', 'is_empty', 'is_not_empty'];
const operatorNames = { equals: '=', not_equals: '≠', contains: '包含', not_contains: '不包含', starts_with: '开头是', ends_with: '结尾是', regex: '正则', in: '属于集合', not_in: '不属于集合', between: '范围', is_empty: '为空', is_not_empty: '不为空' };

function CollectionValue({ value, onChange }) {
  const [text, setText] = useState(JSON.stringify(value ?? []));
  const [valid, setValid] = useState(Array.isArray(value));
  return <input className={inputClass} aria-label={tx('条件值 JSON 数组')} value={text} placeholder='["USD", "CNY"]' onChange={event => {
    setText(event.target.value);
    try { const next = JSON.parse(event.target.value); if (!Array.isArray(next)) throw new Error(); setValid(true); onChange(next); }
    catch { setValid(false); }
  }} onInvalid={event => event.target.setCustomValidity(tx('条件值必须为 JSON 数组'))} ref={input => input?.setCustomValidity(valid ? '' : tx('条件值必须为 JSON 数组'))} />;
}

export default function RuleConditionEditor({ value, onChange, categories, depth = 0 }) {
  const group = ['AND', 'OR', 'NOT'].includes((value.operator || '').toUpperCase());
  const update = patch => onChange({ ...value, ...patch });
  if (group) {
    const children = value.rules || [];
    return <div className="p-2 space-y-2 rounded-xl border border-zinc-200 dark:border-zinc-700 min-w-0">
      <select aria-label={tx('条件组运算符')} className={inputClass} value={value.operator.toUpperCase()} onChange={event => update({ operator: event.target.value })}>
        <option value="AND">{tx('全部满足 (AND)')}</option><option value="OR">{tx('任一满足 (OR)')}</option><option value="NOT">{tx('全部不满足 (NOT)')}</option>
      </select>
      {children.map((child, index) => <div key={index} className="flex gap-1 items-start">
        <div className="flex-1 min-w-0"><RuleConditionEditor depth={depth + 1} categories={categories} value={child} onChange={next => update({ rules: children.map((item, i) => i === index ? next : item) })} /></div>
        <button type="button" aria-label={tx('删除此条件')} className="p-2 text-rose-500" onClick={() => update({ rules: children.filter((_, i) => i !== index) })}>×</button>
      </div>)}
      <div className="flex gap-2 flex-wrap"><button type="button" onClick={() => update({ rules: [...children, { field: 'merchant', operator: 'contains', value: '' }] })}>{tx('添加单条条件')}</button>
        {depth < 11 && <button type="button" onClick={() => update({ rules: [...children, { operator: 'OR', rules: [{ field: 'merchant', operator: 'contains', value: '' }] }] })}>{tx('添加条件组')}</button>}</div>
    </div>;
  }
  const isCategory = ['category', 'category_id'].includes(value.field);
  const isCollection = ['in', 'not_in', 'between'].includes(value.operator);
  const empty = ['is_empty', 'is_not_empty'].includes(value.operator);
  const fieldOptions = fields.includes(value.field) ? fields : [...fields, value.field];
  const operatorOptions = operations.includes(value.operator) ? operations : [...operations, value.operator];
  return <div className="grid grid-cols-2 gap-1">
    <select className={inputClass} aria-label={tx('条件字段')} value={value.field} onChange={event => update({ field: event.target.value, value: '' })}>{fieldOptions.map(field => <option key={field} value={field}>{tx(fieldNames[field] || field)}</option>)}</select>
    <select className={inputClass} aria-label={tx('条件运算符')} value={value.operator} onChange={event => update({ operator: event.target.value, value: ['in', 'not_in', 'between'].includes(event.target.value) ? [] : '' })}>{operatorOptions.map(operator => <option key={operator} value={operator}>{tx(operatorNames[operator] || operator)}</option>)}</select>
    {!empty && <div className="col-span-2">
      {isCollection ? <CollectionValue key={value.operator + value.field} value={value.value} onChange={next => update({ value: next })} /> :
        isCategory ? <select aria-label={tx('分类')} required className={inputClass} value={value.value || ''} onChange={event => update({ value: event.target.value })}><option value="">{tx('选择分类')}</option>{categories.map(category => <option key={category.id} value={category.id}>{category.icon} {categoryLabel(category.name)}</option>)}</select> :
          ['is_reimbursable', 'excluded_from_stats'].includes(value.field) ? <select className={inputClass} value={String(value.value)} onChange={event => update({ value: event.target.value === 'true' })}><option value="true">{tx('是')}</option><option value="false">{tx('否')}</option></select> :
            <input required className={inputClass} aria-label={tx('条件值')} type={value.field === 'amount' ? 'number' : 'text'} step="any" value={value.value ?? ''} onChange={event => update({ value: event.target.value })} />}
    </div>}
  </div>;
}
