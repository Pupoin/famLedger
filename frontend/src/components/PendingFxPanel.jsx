import { tx, useLocale } from "../localization.js";
import { apiErrorMessage } from '../api/errorMessages';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { fetchWithAuth } from '../api/fetchWithAuth';

export default function PendingFxPanel({ accounts = [], onPosted }) {
  useLocale();
  const [items, setItems] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [confirmation, setConfirmation] = useState(null);
  const [bankAmount, setBankAmount] = useState('');
  const [masterAmount, setMasterAmount] = useState('');
  const previousItems = useRef(null);
  const load = useCallback(async () => {
    const response = await fetchWithAuth('/api/v1/pending-transactions');
    if (!response.ok) throw new Error(tx("待换汇记录加载失败"));
    const next = (await response.json()).items || [];
    if (previousItems.current?.length && previousItems.current.some(old => !next.some(row => row.id === old.id))) onPosted?.();
    previousItems.current = next;
    setItems(next);
  }, [onPosted]);
  useEffect(() => {
    load().catch(e => setError(tx(e.message)));
    const timer = setInterval(() => load().catch(e => setError(tx(e.message))), 30000);
    const refresh = () => load().catch(e => setError(tx(e.message)));
    window.addEventListener('pending-fx-changed', refresh);
    return () => { clearInterval(timer); window.removeEventListener('pending-fx-changed', refresh); };
  }, [load]);
  async function act(item, action, body) {
    setBusy(item.id); setError('');
    try {
      const response = await fetchWithAuth(`/api/v1/pending-transactions/${item.id}/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(result.detail, '操作失败，请核对金额'));
      if (result.status === 'pending_fx') setError(tx(result.last_error || '汇率仍不可用，记录保留在待换汇队列'));
      setConfirmation(null); await load();
      if (result.status === 'created' || result.status === 'posted') onPosted?.();
    } catch (e) { setError(tx(e.message)); } finally { setBusy(''); }
  }
  if (!items.length && !error) return null;
  const selectedAccount = accounts.find(a => a.id === confirmation?.account_id);
  const master = accounts.find(a => a.id === selectedAccount?.parent_account_id) || selectedAccount?.parent_account;
  return <section className="my-3 p-4 rounded-xl border border-amber-300 bg-amber-50 dark:bg-zinc-900">
    <h3 className="font-semibold">{tx("待换汇（")} {items.length}）</h3>
    <p className="text-xs text-zinc-500">{tx("这些记录尚未入账，不影响余额、统计和退款额度。系统会自动按交易日期重试。")}</p>
    {error && <p role="alert" className="text-sm text-red-600">{tx(error)}</p>}
    {items.map(item => <div key={item.id} className="flex flex-wrap items-center gap-2 py-2 border-b border-amber-200">
      <span className="flex-1">{item.narration} · {item.original_amount} {item.original_currency} · {item.transacted_at}</span>
      {!item.read_only && <>
        <button disabled={!!busy} onClick={() => act(item, 'retry')}>{tx("重试")}</button>
        <button disabled={!!busy} onClick={() => { setConfirmation(item); setBankAmount(''); setMasterAmount(''); }}>{tx("确认银行结算")}</button>
        <button disabled={!!busy} onClick={() => act(item, 'cancel')}>{tx("取消入账")}</button>
      </>}
    </div>)}
    {confirmation && <form className="mt-3 flex flex-wrap gap-2" onSubmit={e => {
      e.preventDefault();
      if (!selectedAccount) { setError(tx("无法确认账户币种，请刷新账户列表")); return; }
      act(confirmation, 'confirm', { settlement_amount: bankAmount, settlement_currency: selectedAccount.currency,
        ...(masterAmount && master ? {master_settlement_amount: masterAmount, master_settlement_currency: master.currency} : {}) });
    }}>
      <label>{tx("银行实际结算（")} {selectedAccount?.currency}） <input required type="number" min="0.0001" step="0.0001" value={bankAmount} onChange={e => setBankAmount(e.target.value)} className="border rounded p-1 dark:bg-zinc-800" /></label>
      {master && master.currency !== selectedAccount.currency && <label>{tx("主卡实际结算（")} {master.currency} {tx("，可选）")} <input type="number" min="0.0001" step="0.0001" value={masterAmount} onChange={e => setMasterAmount(e.target.value)} className="border rounded p-1 dark:bg-zinc-800" /></label>}
      <button disabled={!!busy} type="submit">{tx("确认并入账")}</button>
      <button type="button" onClick={() => setConfirmation(null)}>{tx("返回")}</button>
    </form>}
  </section>;
}
