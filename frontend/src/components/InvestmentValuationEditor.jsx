import React, { useState } from 'react';
import { tx, useLocale } from '../localization';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { apiErrorMessage } from '../api/errorMessages';
import { localToUTCISO, toLocalISODate, toLocalISOTime } from '../utils/dates';

export default function InvestmentValuationEditor({ transaction, onSaved, onCancel }) {
  useLocale();
  const instant = transaction.occurred_at ? new Date(transaction.occurred_at) : null;
  const [amount, setAmount] = useState(transaction.extra.target_balance);
  const [day, setDay] = useState(instant ? toLocalISODate(instant) : transaction.transacted_at);
  const [time, setTime] = useState(instant ? toLocalISOTime(instant, true) : '00:00:00');
  const [name, setName] = useState(transaction.narration || '');
  const [notes, setNotes] = useState(transaction.notes || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const inputClass = 'mt-1 w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-2 text-zinc-900 dark:text-zinc-100';
  async function save(event) {
    event.preventDefault();
    setSaving(true); setError('');
    try {
      const response = await fetchWithAuth(`/api/v1/transactions/${transaction.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ valuation_amount: amount, occurred_at: localToUTCISO(day, time), narration: name, notes }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiErrorMessage(result.detail, '更新失败'));
      onSaved(result);
    } catch (err) {
      setError(tx(err.message || '更新失败'));
    } finally { setSaving(false); }
  }
  return <form onSubmit={save} data-testid="investment-valuation-editor" className="space-y-3 rounded-xl border-2 border-blue-500/80 bg-blue-50/20 dark:bg-blue-950/20 p-4 text-xs">
    <h3 className="font-bold text-zinc-900 dark:text-white">{tx('编辑投资市值')}</h3>
    <p className="text-zinc-500">{tx('填写当时的投资总市值（含账户现金），盈亏差额和后续市值记录会自动重算。')}</p>
    <label className="block">{tx('投资总市值')} ({transaction.currency})
      <input aria-label={tx('投资总市值')} className={inputClass} type="number" min="0" step="0.0001" required value={amount} onChange={e => setAmount(e.target.value)} />
    </label>
    <div className="grid grid-cols-2 gap-2">
      <label>{tx('日期')}<input className={inputClass} type="date" required value={day} onChange={e => setDay(e.target.value)} /></label>
      <label>{tx('时间')}<input className={inputClass} type="time" step="1" required value={time} onChange={e => setTime(e.target.value)} /></label>
    </div>
    <label className="block">{tx('交易名称 (选填)')}<input className={inputClass} value={name} maxLength={255} onChange={e => setName(e.target.value)} /></label>
    <label className="block">{tx('备注')}<textarea className={inputClass} value={notes} onChange={e => setNotes(e.target.value)} /></label>
    {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
    <div className="flex justify-end gap-2">
      <button type="button" disabled={saving} onClick={onCancel} className="rounded-lg border border-zinc-300 dark:border-zinc-700 px-3 py-2">{tx('取消')}</button>
      <button type="submit" disabled={saving} className="rounded-lg bg-zinc-900 px-3 py-2 text-white dark:bg-white dark:text-zinc-900 disabled:opacity-50">{tx(saving ? '正在更新...' : '保存')}</button>
    </div>
  </form>;
}
