import React, { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { tx, useLocale } from '../localization';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { apiErrorMessage } from '../api/errorMessages';
import { localToUTCISO, toLocalISODate, toLocalISOTime } from '../utils/dates';

export default function InvestmentSetupModal({ account, onClose, onSaved }) {
  useLocale();
  const [loading,setLoading]=useState(true);
  const [mode,setMode]=useState('capital');
  const [amount,setAmount]=useState(String(account.balance || 0));
  const [day,setDay]=useState(toLocalISODate(new Date()));
  const [time,setTime]=useState(toLocalISOTime(new Date(),true));
  const [initialAmount,setInitialAmount]=useState('');
  const [initialDay,setInitialDay]=useState(toLocalISODate(new Date()));
  const [initialTime,setInitialTime]=useState('00:00:00');
  const [details,setDetails]=useState(null);
  const [error,setError]=useState('');
  const [saving,setSaving]=useState(false);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(() => {
    let active=true;
    setLoading(true);setDetails(null);setError('');
    fetchWithAuth(`/api/v1/accounts/${account.id}/investment-settings`).then(async response => {
      const result=await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(result.detail,'加载失败'));
      if (!active) return;
      const nextMode=result.mode || 'capital';
      setDetails(result);setMode(nextMode);
      const value=nextMode==='capital' ? result.capital_amount : result.target_balance;
      setAmount(value ?? String(account.balance || 0));
      const occurredAt=nextMode==='capital' ? result.capital_occurred_at : result.occurred_at;
      const date=occurredAt ? new Date(occurredAt) : new Date();
      setDay(toLocalISODate(date));setTime(toLocalISOTime(date,true));
    }).catch(err => {if(active)setError(tx(err.message || '加载失败'));})
      .finally(() => {if(active)setLoading(false);});
    return () => {active=false;};
  },[account.id]);
  useEffect(() => {
    const previous=document.body.style.overflow;document.body.style.overflow='hidden';
    return () => {document.body.style.overflow=previous;};
  },[]);
  useEffect(() => {
    const close=event=>{if(event.key==='Escape' && !saving){event.preventDefault();event.stopPropagation();onClose();}};
    document.addEventListener('keydown',close,true);
    return()=>document.removeEventListener('keydown',close,true);
  },[saving,onClose]);
  async function save(event) {
    event.preventDefault();setError('');setSaving(true);
    try {
      const payload=mode==='capital'
        ? {mode,capital_amount:amount,capital_occurred_at:localToUTCISO(day,time)}
        : mode==='baseline' ? {mode,target_balance:amount,occurred_at:localToUTCISO(day,time)}
          : {mode,...(details?.can_add_initial ? {initial_amount:initialAmount,initial_occurred_at:localToUTCISO(initialDay,initialTime)} : {})};
      const response=await fetchWithAuth(`/api/v1/accounts/${account.id}/investment-settings`,{
        method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),
      });
      const result=await response.json().catch(()=>({}));
      if(!response.ok) throw new Error(apiErrorMessage(result.detail,'保存失败'));
      window.dispatchEvent(new CustomEvent('accounts-updated'));
      window.dispatchEvent(new CustomEvent('transaction-updated'));
      if(mounted.current){onSaved?.(result);onClose();}
    } catch(err) {if(mounted.current)setError(tx(err.message || '保存失败'));} finally {if(mounted.current)setSaving(false);}
  }
  const input='mt-1 w-full min-w-0 max-w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-2 text-zinc-900 dark:text-zinc-100';
  const capitalMode=mode==='capital';
  const amountLabel=capitalMode ? '基准本金' : '起算总市值';
  const dateLabel=capitalMode ? '本金基准日期' : '起算日期';
  return <div data-settings-modal className="fixed inset-0 z-[60] flex items-center justify-center p-4">
    <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={saving ? undefined : onClose}/>
    <div role="dialog" aria-modal="true" aria-label={tx('投资设置')} data-testid="investment-setup-modal" className="relative max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto overscroll-contain rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 text-xs text-zinc-700 dark:text-zinc-200 shadow-xl">
      <div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-base font-bold">{tx('投资设置')}</h2><button type="button" disabled={saving} aria-label={tx('关闭')} onClick={onClose}><X className="h-4 w-4"/></button></div>
      {loading ? <p>{tx('正在加载...')}</p> : <form onSubmit={save} onChange={()=>setError('')} className="space-y-4">
        <p>{account.name} · {account.currency}</p>
        <fieldset className="grid gap-2"><legend className="mb-2 font-semibold">{tx('投资统计起点')}</legend>
          {[['capital','从指定日期的本金开始'],['baseline','从指定日期的市值开始'],['history','使用完整历史投入与提取']].map(([key,label])=><label key={key} className="flex items-center gap-2 rounded-lg border border-zinc-200 dark:border-zinc-700 p-3"><input type="radio" name="investment-start-mode" value={key} checked={mode===key} onChange={()=>setMode(key)}/>{tx(label)}</label>)}
        </fieldset>
        {mode!=='history' ? <>
          <p data-testid={capitalMode ? 'investment-capital-basis-note' : undefined} className="leading-relaxed text-zinc-500">{tx(capitalMode
            ? '本金基准只用于收益计算，可以早于建账期初；不会新增或修改流水，也不改变账户余额。后续期初记录作为市值参考，不会重复计为入金。'
            : '此市值作为收益率起点，不当作历史投入本金。保存会新增或更新对应市值记录，之后继续用“新建余额”更新市值。')}</p>
          <label className="block">{tx(amountLabel)} ({account.currency})<input aria-label={tx(amountLabel)} data-testid="investment-basis-amount" type="number" min={capitalMode ? '0.0001' : '0'} step="0.0001" required className={input} value={amount} onChange={e=>setAmount(e.target.value)}/></label>
          <div className="grid grid-cols-2 gap-2"><label className="min-w-0">{tx(dateLabel)}<input aria-label={tx(dateLabel)} data-testid="investment-basis-date" className={input} type="date" required value={day} onChange={e=>setDay(e.target.value)}/></label><label className="min-w-0">{tx('时间')}<input aria-label={tx('时间')} data-testid="investment-basis-time" className={input} type="time" step="1" required value={time} onChange={e=>setTime(e.target.value)}/></label></div>
        </> : <>
          <p className="leading-relaxed text-zinc-500">{tx('请确认期初金额是真实投入，并补齐全部入金、提现。本金由这些流水累计；投资账户之间互转在组合统计中抵消。')}</p>
          {details?.can_add_initial ? <>
            <label className="block">{tx('初始投入本金')} ({account.currency})<input aria-label={tx('初始投入本金')} type="number" min="0.0001" step="0.0001" required className={input} value={initialAmount} onChange={e=>setInitialAmount(e.target.value)}/></label>
            <div className="grid grid-cols-2 gap-2"><label className="min-w-0">{tx('投入日期')}<input aria-label={tx('投入日期')} className={input} type="date" required value={initialDay} onChange={e=>setInitialDay(e.target.value)}/></label><label className="min-w-0">{tx('时间')}<input aria-label={tx('时间')} className={input} type="time" step="1" required value={initialTime} onChange={e=>setInitialTime(e.target.value)}/></label></div>
            <p className="text-zinc-500">{tx('保存将补录一笔期初投入，不计日常收入。已有投入流水时不会重复创建本金。')}</p>
          </> : <p className="rounded-lg bg-zinc-50 dark:bg-zinc-800 p-3">{tx('将使用已有期初和资金流水计算。如需独立指定本金，请选择“从指定日期的本金开始”。')}</p>}
        </>}
        {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
        <div className="flex justify-end gap-2"><button type="button" disabled={saving} className="rounded-lg border border-zinc-300 dark:border-zinc-700 px-3 py-2" onClick={onClose}>{tx('取消')}</button><button type="submit" disabled={saving || !details} className="rounded-lg bg-zinc-900 dark:bg-white px-3 py-2 text-white dark:text-zinc-900 disabled:opacity-50">{tx(saving?'保存中...':'保存投资设置')}</button></div>
      </form>}
    </div>
  </div>;
}
