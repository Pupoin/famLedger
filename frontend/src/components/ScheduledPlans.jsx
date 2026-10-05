import { createPortal } from 'react-dom';
import React, { useCallback, useEffect, useState, useRef } from 'react';
import { tx, useLocale } from '../localization';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';
import { useCurrency } from '../CurrencyContext';
import { toLocalISODate } from '../utils/dates';
import AccountSelectDropdown from './AccountSelectDropdown';
import { getAccountClassification } from '../utils/accountTypes';

const methods = {equal_installment:'等额本息',equal_principal:'等额本金',interest_only:'仅还利息',principal_only:'只还本金',custom:'自定义还款'};
const statuses = {active:'执行中',paused:'已暂停',cancelled:'已取消',planned:'计划中',awaiting:'待确认扣款',posted:'已记账',reconciled:'已关联银行流水',skipped:'已跳过',failed:'执行失败',undone:'已撤销'};
const fieldClass = 'w-full min-w-0 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100';
const buttonClass = 'rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-2 text-xs font-semibold hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-40';
const primaryClass = 'rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 px-4 py-2 text-xs font-semibold disabled:opacity-40';

async function request(path, options) {
  const response = await fetchWithAuth(`/api/v1/plans${path}`, options);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? tx(body.detail) : tx('请检查计划设置'));
  return body;
}
const jsonBody = (body, method='POST') => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

function Field({label, children}) {
  return <label className="block min-w-0 space-y-1"><span className="block text-xs font-medium text-zinc-600 dark:text-zinc-400">{tx(label)}</span>{children}</label>;
}

function PlanEditor({plan, account, accounts, onClose, onSaved}) {
  useLocale();
  const { showToast } = useToast();
  const { currencies } = useCurrency();
  const now = new Date();
  const loanAccount = ['loan','mortgage'].includes(account?.account_type);
  const firstDue = new Date(now.getFullYear(), now.getMonth()+1, Math.min(now.getDate(),28));
  const [form, setForm] = useState(() => plan ? {
    name:plan.name,kind:plan.kind,account_id:plan.account_id,destination_id:plan.destination_id,
    amount:plan.amount,currency:plan.currency,start_date:plan.edit_start_date||plan.start_date,end_date:plan.end_date||'',
    frequency:plan.frequency,interval:plan.interval,occurrence_limit:plan.occurrence_limit,
    timezone_name:plan.timezone_name,execution_mode:plan.execution_mode,loan:plan.config.loan,
  } : {
    name:account?.name || '',kind:loanAccount?'loan':'transfer',account_id:loanAccount?'':account?.id||'',destination_id:loanAccount?account.id:'',
    amount:'100',currency:account?.currency||accounts[0]?.currency||'CNY',
    start_date:toLocalISODate(loanAccount?firstDue:now),end_date:'',frequency:'monthly',interval:1,
    occurrence_limit:loanAccount?360:120,timezone_name:Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC',execution_mode:'confirm',
    loan:loanAccount?{term_months:360,interest_start_date:toLocalISODate(now),day_count:'monthly',fee:0,interest_free_periods:[],interest_only_periods:[],
      rates:[{effective_date:toLocalISODate(now),annual_rate:0}],phases:[{from_period:1,method:'equal_installment',amount:null,interest_treatment:null}]}:null,
  });
  const [busy,setBusy]=useState(false);
  const [preview,setPreview]=useState(null);
  const [advancedOpen,setAdvancedOpen]=useState(()=>!!(plan?.config.loan?.phases?.length>1||plan?.config.loan?.interest_free_periods?.length||plan?.config.loan?.interest_only_periods?.length));
  const modalRef=useRef(null);
  const closeRef=useRef(onClose),busyRef=useRef(busy);
  closeRef.current=onClose;busyRef.current=busy;
  useEffect(()=>{
    const previousOverflow=document.body.style.overflow;
    const previousFocus=document.activeElement;
    document.body.style.overflow='hidden';
    modalRef.current?.querySelector('input')?.focus();
    const keys=event=>{
      if(event.key==='Escape'&&!busyRef.current){event.preventDefault();closeRef.current();}
      if(event.key==='Tab'){
        const elements=[...modalRef.current.querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')].filter(e=>e.offsetParent!==null&&e.tabIndex>=0);
        const first=elements[0],last=elements.at(-1);
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',keys);
    return()=>{document.body.style.overflow=previousOverflow;document.removeEventListener('keydown',keys);previousFocus?.focus();};
  },[]);
  const change = (key,value) => {setPreview(null);setForm(prev=>({...prev,[key]:value}));};
  const changeLoan = (key,value) => {setPreview(null);setForm(prev=>({...prev,loan:{...prev.loan,[key]:value}}));};
  const changeStage = (kind,index,key,value) => {
    setPreview(null);
    setForm(prev=>({...prev,loan:{...prev.loan,[kind]:prev.loan[kind].map((row,i)=>i===index?{...row,[key]:value}:row)}}));
  };
  const payload = () => ({...form,end_date:form.end_date||null,amount:form.kind==='loan'?0:form.amount,
    occurrence_limit:form.kind==='loan'?Number(form.loan.term_months):Number(form.occurrence_limit),interval:Number(form.interval),
    loan:form.loan?{...form.loan,term_months:Number(form.loan.term_months),phases:form.loan.phases.map(p=>({...p,from_period:Number(p.from_period),
      amount:['custom','principal_only'].includes(p.method)?p.amount:null,interest_treatment:p.method==='principal_only'?p.interest_treatment:null}))}:null});
  const submit = async (event,onlyPreview=false) => {
    event.preventDefault();setBusy(true);
    try {
      const result=await request(onlyPreview?(plan?`/${plan.id}/preview`:'/preview'):plan?`/${plan.id}`:'',jsonBody(payload(),!onlyPreview&&plan?'PUT':'POST'));
      if(onlyPreview)setPreview(result.occurrences);
      else {onSaved(result);showToast(tx('计划已保存'),'success');}
    } catch(error) {showToast(error.message,'error');} finally {setBusy(false);}
  };
  const writable = accounts.filter(a=>a.can_edit===true&&a.is_active!==false);
  const sourceOptions = form.kind==='loan'?writable.filter(a=>getAccountClassification(a)==='asset'):writable;
  return createPortal(<div ref={modalRef} className="fixed inset-0 z-[100] bg-black/40 flex items-center justify-center sm:p-5" role="dialog" aria-modal="true" aria-label={tx(form.kind==='loan'?'配置还款计划':'定期转账')}>
    <div className="flex flex-col w-full max-w-2xl h-full sm:h-auto sm:max-h-[90dvh] bg-white dark:bg-zinc-900 sm:rounded-2xl shadow-xl">
      <header className="flex justify-between items-center gap-3 p-4 border-b border-zinc-200 dark:border-zinc-800">
        <h2 className="font-bold text-base">{tx(form.kind==='loan'?'配置还款计划':'定期转账')}</h2>
        <button type="button" className={buttonClass} disabled={busy} onClick={onClose}>{tx('关闭')}</button>
      </header>
      <form data-testid="plan-editor" className="overflow-y-auto overscroll-contain p-4 space-y-4" onSubmit={submit}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="计划名称"><input className={fieldClass} value={form.name} maxLength={100} required onChange={e=>change('name',e.target.value)}/></Field>
          <Field label="扣款账户"><AccountSelectDropdown accounts={sourceOptions} value={form.account_id} testId="plan-source" onChange={e=>{
            change('account_id',e.target.value);if(form.kind==='transfer')change('currency',accounts.find(a=>a.id===e.target.value)?.currency||form.currency);
          }}/></Field>
          <Field label={form.kind==='loan'?'贷款账户':'转入账户'}><AccountSelectDropdown accounts={writable.filter(a=>a.id!==form.account_id&&(form.kind!=='loan'||['loan','mortgage'].includes(a.account_type)))} value={form.destination_id} testId="plan-destination" onChange={e=>{
            change('destination_id',e.target.value);if(form.kind==='loan')change('currency',accounts.find(a=>a.id===e.target.value)?.currency||form.currency);
          }}/></Field>
          {form.kind==='transfer'&&<Field label="每期转账金额"><input className={fieldClass} type="number" min="0.0001" step="0.0001" required value={form.amount} onChange={e=>change('amount',e.target.value)}/></Field>}
          <Field label="计划币种"><select className={fieldClass} value={form.currency} onChange={e=>change('currency',e.target.value)}>
            {[...new Set([form.currency,...(currencies||['CNY','USD','EUR','HKD','JPY']).map(c=>typeof c==='object'?c.code:c)])].map(code=><option key={code} value={code}>{code}</option>)}
          </select></Field>
          <Field label={plan?'下次执行日期':'首次执行日期'}><input className={fieldClass} type="date" required value={form.start_date} onChange={e=>change('start_date',e.target.value)}/></Field>
          <Field label="执行模式"><select className={fieldClass} value={form.execution_mode} onChange={e=>change('execution_mode',e.target.value)}>
            <option value="confirm">{tx('等待银行流水确认')}</option><option value="auto">{tx('到期自动记账')}</option>
          </select></Field>
          {form.kind==='transfer'&&<>
            <Field label="执行周期"><select className={fieldClass} value={form.frequency} onChange={e=>change('frequency',e.target.value)}>
              {Object.entries({weekly:'每周',monthly:'每月',quarterly:'每季度',yearly:'每年'}).map(([value,label])=><option key={value} value={value}>{tx(label)}</option>)}
            </select></Field>
            <Field label="间隔周期数"><input className={fieldClass} type="number" min="1" max="120" required value={form.interval} onChange={e=>change('interval',e.target.value)}/></Field>
            <Field label="执行次数"><input className={fieldClass} type="number" min="1" max="1200" required value={form.occurrence_limit} onChange={e=>change('occurrence_limit',e.target.value)}/></Field>
            <Field label="结束日期（可选）"><input className={fieldClass} type="date" value={form.end_date} min={form.start_date} onChange={e=>change('end_date',e.target.value)}/></Field>
          </>}
          <Field label="执行时区"><input className={fieldClass} required value={form.timezone_name} onChange={e=>change('timezone_name',e.target.value)}/></Field>
        </div>
        {plan&&<p className="text-xs text-zinc-500">{tx('修改仅影响未处理期次，已处理期次保留原设置。')}</p>}
        {form.kind==='loan'&&<p className="text-xs text-zinc-500">{tx('贷款计划币种需与所选贷款账户一致。')}</p>}
        {form.loan&&<>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="还款期数（月）"><input className={fieldClass} type="number" required min="1" max="1200" value={form.loan.term_months} onChange={e=>changeLoan('term_months',e.target.value)}/></Field>
            <Field label="计息开始日期"><input className={fieldClass} type="date" required value={form.loan.interest_start_date} onChange={e=>changeLoan('interest_start_date',e.target.value)}/></Field>
            <Field label="计息方式"><select className={fieldClass} value={form.loan.day_count} onChange={e=>changeLoan('day_count',e.target.value)}>
              <option value="monthly">{tx('按月计息')}</option><option value="actual_365">{tx('实际天数 / 365')}</option><option value="actual_360">{tx('实际天数 / 360')}</option>
            </select></Field>
            <Field label="每期手续费"><input className={fieldClass} type="number" min="0" step="0.01" value={form.loan.fee} onChange={e=>changeLoan('fee',e.target.value)}/></Field>
            <Field label="常规还款方式"><select className={fieldClass} value={form.loan.phases[0].method} onChange={e=>changeStage('phases',0,'method',e.target.value)}>
              {Object.entries(methods).filter(([value])=>['equal_installment','equal_principal'].includes(value)||value===form.loan.phases[0].method).map(([value,label])=><option key={value} value={value}>{tx(label)}</option>)}
            </select></Field>
          </div>
          <section className="space-y-2"><h3 className="font-semibold text-sm">{tx('利率阶段')}</h3>
            {form.loan.rates.map((row,i)=><div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2 items-end" key={i}>
              <Field label="生效日期"><input className={fieldClass} type="date" required value={row.effective_date} onChange={e=>changeStage('rates',i,'effective_date',e.target.value)}/></Field>
              <Field label="年利率（%）"><input className={fieldClass} type="number" required min="0" max="100" step="0.0001" value={row.annual_rate} onChange={e=>changeStage('rates',i,'annual_rate',e.target.value)}/></Field>
              <button type="button" className={buttonClass} disabled={form.loan.rates.length===1} aria-label={tx('删除阶段')} onClick={()=>changeLoan('rates',form.loan.rates.filter((_,j)=>j!==i))}>×</button>
            </div>)}
            <button type="button" className={buttonClass} onClick={()=>changeLoan('rates',[...form.loan.rates,{effective_date:form.start_date,annual_rate:0}])}>{tx('新增利率阶段')}</button>
          </section>
          <details data-testid="loan-advanced-settings" className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3" open={advancedOpen} onToggle={e=>setAdvancedOpen(e.currentTarget.open)}>
            <summary className="cursor-pointer font-semibold text-sm">{tx('高级设置')}</summary>
            <div className="mt-4 space-y-5">
              {['interest_free_periods','interest_only_periods'].map(kind=><section key={kind} className="space-y-2">
                <h3 className="font-semibold text-sm">{tx(kind==='interest_free_periods'?'免息期':'仅还利息时间段')}</h3>
                <p className="text-xs text-zinc-500">{tx(kind==='interest_free_periods'?'免息期间不计利息，结束日期包含当天；本金和手续费按计划处理。':'按还款日判断是否仅还利息；区间结束后恢复常规本金及利息还款。')}</p>
                {(form.loan[kind]||[]).map((row,i)=><div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2 items-end">
                  <Field label={kind==='interest_free_periods'?'免息开始日期':'仅还利息开始日期'}><input className={fieldClass} type="date" required value={row.start_date} onChange={e=>changeStage(kind,i,'start_date',e.target.value)}/></Field>
                  <Field label={kind==='interest_free_periods'?'免息结束日期（含当天）':'仅还利息结束日期（含当天）'}><input className={fieldClass} type="date" required min={row.start_date} value={row.end_date} onChange={e=>changeStage(kind,i,'end_date',e.target.value)}/></Field>
                  <button type="button" className={buttonClass} aria-label={tx(kind==='interest_free_periods'?'删除免息期':'删除仅还利息时间段')} onClick={()=>changeLoan(kind,form.loan[kind].filter((_,j)=>j!==i))}>×</button>
                </div>)}
                <button type="button" className={buttonClass} onClick={()=>changeLoan(kind,[...(form.loan[kind]||[]),{start_date:kind==='interest_free_periods'?form.loan.interest_start_date:form.start_date,end_date:form.start_date}])}>{tx(kind==='interest_free_periods'?'新增免息期':'新增仅还利息时间段')}</button>
              </section>)}
          <section className="space-y-2"><h3 className="font-semibold text-sm">{tx('还款阶段')}</h3>
            {form.loan.phases.map((row,i)=><div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 grid grid-cols-1 sm:grid-cols-2 gap-3" key={i}>
              <Field label="从第几期开始"><input className={fieldClass} type="number" min="1" max={form.loan.term_months} required value={row.from_period} onChange={e=>changeStage('phases',i,'from_period',e.target.value)}/></Field>
              <Field label="还款方式"><select className={fieldClass} value={row.method} onChange={e=>changeStage('phases',i,'method',e.target.value)}>
                {Object.entries(methods).filter(([value])=>value!=='interest_only'||row.method==='interest_only').map(([value,label])=><option value={value} key={value}>{tx(label)}</option>)}
              </select></Field>
              {['principal_only','custom'].includes(row.method)&&<Field label={row.method==='principal_only'?'每期偿还本金':'每期还款总额'}>
                <input className={fieldClass} type="number" min="0.01" step="0.01" required value={row.amount||''} onChange={e=>changeStage('phases',i,'amount',e.target.value)}/>
              </Field>}
              {row.method==='principal_only'&&<Field label="利息处理"><select className={fieldClass} required value={row.interest_treatment||''} onChange={e=>changeStage('phases',i,'interest_treatment',e.target.value)}>
                <option value="">{tx('选择利息处理')}</option><option value="waive">{tx('该阶段免息')}</option>
                <option value="defer">{tx('利息延期支付')}</option><option value="capitalize">{tx('利息计入本金')}</option>
              </select></Field>}
              {i>0&&<button type="button" className={buttonClass} onClick={()=>changeLoan('phases',form.loan.phases.filter((_,j)=>j!==i))}>{tx('删除阶段')}</button>}
            </div>)}
            <button type="button" className={buttonClass} onClick={()=>changeLoan('phases',[...form.loan.phases,{from_period:Math.min(Number(form.loan.term_months),Number(form.loan.phases.at(-1).from_period)+12),method:'equal_installment',amount:null,interest_treatment:null}])}>{tx('新增还款阶段')}</button>
          </section>
            </div>
          </details>
        </>}
        <p className="text-xs text-zinc-500 leading-relaxed">{tx('未来计划不影响实际余额。自动记账不会向银行发起扣款。')}</p>
        {form.kind==='loan'&&<p className="text-xs text-zinc-500">{tx('最后一期包含剩余本金和延期利息；修改阶段只影响未来期次。')}</p>}
        <div className="flex flex-wrap justify-end gap-2"><button type="submit" className={buttonClass} disabled={busy} onClick={e=>{
          if(e.currentTarget.form.reportValidity())submit(e,true);else e.preventDefault();
        }}>{tx('预览计划')}</button><button type="submit" className={primaryClass} disabled={busy||!form.account_id||!form.destination_id}>{tx('保存计划')}</button></div>
        {preview&&<div data-testid="plan-preview" className="rounded-xl bg-zinc-50 dark:bg-zinc-800 p-3 space-y-2">
          {preview.slice(0,6).map(row=><div key={row.number} className="flex flex-wrap justify-between gap-2 text-xs"><span>{row.due_date}</span><span className="font-mono">{row.total} {row.currency}</span></div>)}
          <span className="text-xs text-zinc-500">{tx('共 {p0} 期',{p0:preview.length})}</span>
        </div>}
      </form>
    </div>
  </div>,document.body);
}

export default function ScheduledPlans({account=null,onChanged,onSelectTransaction}) {
  const locale=useLocale();
  const {showToast}=useToast();
  const {privacyMode}=useCurrency();
  const [plans,setPlans]=useState([]),[accounts,setAccounts]=useState([]),[detail,setDetail]=useState(null);
  const [editor,setEditor]=useState(null),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
  const [bankChoices,setBankChoices]=useState(null),[prepay,setPrepay]=useState(null);
  const [settlement,setSettlement]=useState(null);
  const money=(amount,currency)=>privacyMode?'••••••':new Intl.NumberFormat(locale,{style:'currency',currency}).format(Number(amount||0));
  const reload=useCallback(async()=>{
    setLoading(true);
    try{
      const [list,response]=await Promise.all([request(account?`?account_id=${account.id}`:''),fetchWithAuth('/api/v1/accounts')]);
      if(!response.ok)throw new Error(tx('账户加载失败'));
      const accts=await response.json();setPlans(list.items);setAccounts(accts.items||[]);
    }catch(error){showToast(error.message,'error');}finally{setLoading(false);}
  },[account?.id,showToast]);
  useEffect(()=>{reload();},[reload]);
  const run=async(path,body,method='POST')=>{
    setBusy(true);try{const result=await request(path,jsonBody(body,method));setDetail(result);await reload();onChanged?.();return true;}
    catch(error){showToast(error.message,'error');return false;}finally{setBusy(false);}
  };
  const open=async(plan)=>{try{setDetail(await request(`/${plan.id}`));setBankChoices(null);setPrepay(null);setSettlement(null);}catch(error){showToast(error.message,'error');}};
  const edit=async(plan)=>{try{setEditor(await request(`/${plan.id}`));}catch(error){showToast(error.message,'error');}};
  const link=async(row)=>{
    try{const result=await request(`/${detail.id}/candidates/${row.number}`);setBankChoices({row,items:result.items});}
    catch(error){showToast(error.message,'error');}
  };
  const loanAccount=['loan','mortgage'].includes(account?.account_type);
  const canCreate=loanAccount?account.can_manage===true||account.is_owner===true:
    (!account||account.can_edit===true)&&accounts.filter(a=>a.can_edit&&a.is_active!==false).length>=2;
  return <section data-testid="scheduled-plans" className="space-y-4 text-zinc-900 dark:text-zinc-100">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-bold text-sm">{tx(loanAccount?'还款计划':'计划')}</h2>
      {canCreate&&(!loanAccount||!plans.some(p=>p.kind==='loan'&&p.destination_id===account.id&&p.status!=='cancelled'))&&<button className={primaryClass} data-testid="new-plan" onClick={()=>setEditor({})}>{tx(loanAccount?'配置还款计划':'新增定期转账')}</button>}
    </div>
    {loading?<p className="text-sm text-zinc-500">{tx('加载中...')}</p>:!plans.length?<p className="p-8 rounded-xl border border-zinc-200 dark:border-zinc-800 text-center text-sm text-zinc-500">{tx('暂无计划')}</p>:<div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      {plans.map(plan=><div key={plan.id} className="min-w-0 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
        <button data-testid="scheduled-plan-card" className="w-full min-w-0 text-left p-4 space-y-2" onClick={()=>open(plan)}>
        <div className="flex flex-wrap items-start justify-between gap-2"><strong className="text-sm break-words min-w-0">{plan.name}</strong><span className="text-xs text-zinc-500">{tx(statuses[plan.status])}</span></div>
        <p className="text-xs text-zinc-500 break-words">{plan.account_name} → {plan.destination_name}</p>
        <div className="flex flex-wrap justify-between gap-2 text-xs"><span>{plan.next?.due_date||tx('计划已完成')}</span><span className="font-mono font-semibold">{plan.next?money(plan.next.total,plan.next.currency):''}</span></div>
        {plan.pause_reason&&<p className="text-xs text-red-500 break-words">{tx(plan.pause_reason)}</p>}
        </button>
        {plan.can_manage&&<div className="px-4 pb-4"><button data-testid="edit-plan" className={buttonClass} onClick={()=>edit(plan)}>{tx('编辑')}</button></div>}
      </div>)}
    </div>}
    {detail&&<div data-testid="plan-detail" className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-4">
      <div className="flex flex-wrap gap-2 items-center justify-between"><h3 className="font-bold text-sm break-words">{detail.name}</h3>
        <button className={buttonClass} onClick={()=>{setDetail(null);setBankChoices(null);setPrepay(null);setSettlement(null);}}>{tx('关闭')}</button>
      </div>
      {detail.kind==='loan'&&<div className="grid grid-cols-2 gap-3 text-xs">
        <div>{tx('剩余本金')}<strong className="block mt-1 font-mono text-base">{money(detail.loan_balance,detail.currency)}</strong></div>
        <div>{tx('当前年利率')}<strong className="block mt-1 text-base">{detail.current_rate}%</strong></div>
        <div>{tx('下次还款日')}<span className="block mt-1 font-mono">{detail.next?.due_date||'—'}</span></div>
        <div>{tx('预计扣款')}<span className="block mt-1 font-mono">{detail.next?money(detail.next.total,detail.next.currency):'—'}</span></div>
        <div>{tx('未付利息')}<span className="block mt-1 font-mono">{money(detail.unpaid_interest,detail.currency)}</span></div>
        <div>{tx('已还本金')}<span className="block mt-1 font-mono">{money(detail.paid_totals.principal,detail.currency)}</span></div>
        <div>{tx('已付利息')}<span className="block mt-1 font-mono">{money(detail.paid_totals.interest,detail.currency)}</span></div>
        <div>{tx('已付手续费')}<span className="block mt-1 font-mono">{money(detail.paid_totals.fee,detail.currency)}</span></div>
        {detail.next_rate_change&&<div className="col-span-2">{tx('下次利率调整')}<span className="block mt-1 font-mono">{detail.next_rate_change.effective_date} · {detail.next_rate_change.annual_rate}%</span></div>}
        {Object.entries(detail.paid_totals_by_currency||{}).filter(([code])=>code!==detail.currency).map(([code,totals])=><div key={code} className="col-span-2">
          {tx('已支付（历史币种）')} · {code}<span className="block mt-1">{tx('本金')} {money(totals.principal,code)} · {tx('利息')} {money(totals.interest,code)} · {tx('手续费')} {money(totals.fee,code)}</span>
        </div>)}
      </div>}
      {detail.kind==='loan'&&(detail.config.loan.interest_free_periods?.length||detail.config.loan.interest_only_periods?.length)?<div className="space-y-2 text-xs">
        <h4 className="font-semibold">{tx('高级设置')}</h4>
        {(detail.config.loan.interest_free_periods||[]).map((period,i)=><p key={`free-${i}`}>{tx('免息期')} · {period.start_date} — {period.end_date}</p>)}
        {(detail.config.loan.interest_only_periods||[]).map((period,i)=><p key={`only-${i}`}>{tx('仅还利息时间段')} · {period.start_date} — {period.end_date}</p>)}
        {!!detail.config.loan.interest_only_periods?.length&&<p className="text-zinc-500">{tx('仅还利息区间结束后，后续期次自动恢复本金加利息。')}</p>}
      </div>:null}
      {detail.can_manage&&<div className="flex flex-wrap gap-2">
        <button disabled={busy} className={buttonClass} onClick={()=>setEditor(detail)}>{tx('编辑')}</button>
        {detail.status!=='cancelled'&&<>
          <button disabled={busy} className={buttonClass} onClick={()=>run(`/${detail.id}/status`,{status:detail.status==='paused'?'active':'paused'},'PATCH')}>{tx(detail.status==='paused'?'恢复计划':'暂停计划')}</button>
          <button disabled={busy} className={buttonClass} onClick={()=>{if(window.confirm(tx('取消计划会停止后续执行，保留已发生流水。')))run(`/${detail.id}/status`,{status:'cancelled'},'PATCH');}}>{tx('取消计划')}</button></>}
        {detail.kind==='loan'&&detail.status==='active'&&Number(detail.loan_balance)>0&&<button className={buttonClass} onClick={()=>setPrepay({amount:'',payment_date:toLocalISODate(new Date()),strategy:['equal_installment','equal_principal'].includes(detail.next?.method)?'reduce_payment':'keep_schedule'})}>{tx('提前还款')}</button>}
      </div>}
      {prepay&&<form className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-xl bg-zinc-50 dark:bg-zinc-800 p-3" onSubmit={async e=>{
        e.preventDefault();if(await run(`/${detail.id}/prepay`,prepay))setPrepay(null);
      }}>
        <Field label="提前偿还本金"><input className={fieldClass} type="number" min="0.01" max={detail.loan_balance} step="0.01" required value={prepay.amount} onChange={e=>setPrepay({...prepay,amount:e.target.value})}/></Field>
        <Field label="实际支付日期"><input className={fieldClass} type="date" max={toLocalISODate(new Date())} required value={prepay.payment_date} onChange={e=>setPrepay({...prepay,payment_date:e.target.value})}/></Field>
        <Field label="后续还款调整"><select className={fieldClass} value={prepay.strategy} onChange={e=>setPrepay({...prepay,strategy:e.target.value})}>{['equal_installment','equal_principal'].includes(detail.next?.method)&&<option value="reduce_payment">{tx('降低后续月供')}</option>}{detail.next?.method==='equal_installment'&&<option value="reduce_term">{tx('缩短还款期限')}</option>}<option value="keep_schedule">{tx('保持原还款安排')}</option></select></Field>
        {accounts.find(a=>a.id===detail.account_id)?.currency!==detail.currency&&<Field label="实际扣款金额（扣款账户币种）"><input className={fieldClass} type="number" min="0.0001" step="0.0001" required value={prepay.bank_amount||''} onChange={e=>setPrepay({...prepay,bank_amount:e.target.value})}/></Field>}
        <button type="submit" disabled={busy} className={primaryClass}>{tx('确认提前还款')}</button>
      </form>}
      {bankChoices&&<div className="rounded-xl bg-zinc-50 dark:bg-zinc-800 p-3 space-y-2">
        <strong className="text-xs">{tx('选择已发生的银行扣款')}</strong>
        {!bankChoices.items.length&&<p className="text-xs text-zinc-500">{tx('未找到金额和币种一致的扣款流水')}</p>}
        {bankChoices.items.map(item=><button key={item.id} disabled={busy} className={`${buttonClass} w-full text-left break-words`} onClick={async()=>{
          if(await run(`/${detail.id}/occurrences/${bankChoices.row.number}`,{action:'link',transaction_id:item.id}))setBankChoices(null);
        }}>{item.date} · {item.narration} · {money(item.amount,item.currency)}</button>)}
        <button className={buttonClass} onClick={()=>setBankChoices(null)}>{tx('关闭')}</button>
      </div>}
      {settlement&&<form className="rounded-xl bg-zinc-50 dark:bg-zinc-800 p-3 space-y-3" onSubmit={async e=>{
        e.preventDefault();if(await run(`/${detail.id}/occurrences/${settlement.number}`,{action:'post',bank_amount:settlement.amount}))setSettlement(null);
      }}>
        <Field label="实际扣款金额（扣款账户币种）"><input className={fieldClass} type="number" min="0.0001" step="0.0001" required value={settlement.amount} onChange={e=>setSettlement({...settlement,amount:e.target.value})}/></Field>
        <span className="text-xs font-mono">{accounts.find(a=>a.id===(detail.occurrences.find(r=>r.number===settlement.number)?.account_id||detail.account_id))?.currency}</span>
        <div className="flex gap-2"><button type="submit" disabled={busy} className={primaryClass}>{tx('确认已扣款')}</button><button type="button" className={buttonClass} onClick={()=>setSettlement(null)}>{tx('关闭')}</button></div>
      </form>}
      <p className="text-xs text-zinc-500">{tx('计划金额使用贷款或转账原币；跨币种实际结算在入账时保存。')}</p>
      <div className="max-h-[65dvh] overflow-y-auto space-y-2">
        {(detail.occurrences||[]).map(row=><div key={row.number} data-testid="plan-occurrence" className="border border-zinc-200 dark:border-zinc-800 rounded-xl p-3 space-y-2">
          <div className="flex flex-wrap justify-between gap-2 text-xs"><span className="font-mono">{row.due_date} · {tx('第 {p0} 期',{p0:row.number})}</span><span>{tx(statuses[row.status])}</span></div>
          <div className="flex flex-wrap justify-between gap-2"><strong className="text-sm font-mono">{money(row.total,row.currency)}</strong>
            {detail.kind==='loan'&&<span className="text-xs text-zinc-500">{tx('本金')} {money(row.principal,row.currency)} · {tx('利息')} {money(row.interest,row.currency)} · {tx('手续费')} {money(row.fee,row.currency)}</span>}
          </div>
          <p className="text-xs text-zinc-500 break-words">{accounts.find(a=>a.id===row.account_id)?.name} → {accounts.find(a=>a.id===row.destination_id)?.name}</p>
          {(Number(row.accrued)>0||Number(row.capitalized)>0)&&<p className="text-xs text-zinc-500">{tx(Number(row.accrued)>0?'延期利息':'计入本金的利息')} {money(Number(row.accrued)>0?row.accrued:row.capitalized,row.currency)}</p>}
          {row.last_error&&<p className="text-xs text-red-500">{tx(row.last_error)}</p>}
          <div className="flex flex-wrap gap-2">
            {row.transaction_ids?.map(id=><button key={id} className={buttonClass} onClick={()=>onSelectTransaction?.(id)}>{tx('查看流水')}</button>)}
            {detail.can_manage&&<>
              {['posted','reconciled','skipped'].includes(row.status)?<button className={buttonClass} disabled={busy} onClick={()=>{if(window.confirm(tx('撤销本期会恢复记账前的余额。')))run(`/${detail.id}/occurrences/${row.number}`,{action:'undo'});}}>{tx('撤销本期')}</button>:detail.status==='active'&&<>
                {row.due_date<=toLocalISODate(new Date())&&<><button className={buttonClass} disabled={busy} onClick={()=>{
                  if(Number(row.total)>0&&accounts.find(a=>a.id===row.account_id)?.currency!==row.currency)setSettlement({number:row.number,amount:''});
                  else run(`/${detail.id}/occurrences/${row.number}`,{action:'post'});
                }}>{tx(Number(row.total)>0?'确认已扣款':'确认本期')}</button>{Number(row.total)>0&&<button className={buttonClass} disabled={busy} onClick={()=>link(row)}>{tx('关联银行流水')}</button>}</>}
                <button className={buttonClass} disabled={busy} onClick={()=>run(`/${detail.id}/occurrences/${row.number}`,{action:'skip'})}>{tx('跳过本期')}</button>
              </>}
            </>}
          </div>
        </div>)}
        {(detail.prepayments||[]).map(row=><div key={row.id} className="border border-zinc-200 dark:border-zinc-800 rounded-xl p-3 text-xs space-y-2">
          <div>{row.due_date} · {tx('提前还款')} · {money(row.snapshot.total,row.currency)}</div>
          {detail.can_manage&&['posted','reconciled'].includes(row.status)&&<button disabled={busy} className={buttonClass} onClick={()=>run(`/${detail.id}/occurrences/${row.number}`,{action:'undo'})}>{tx('撤销本期')}</button>}
        </div>)}
      </div>
    </div>}
    {editor&&<PlanEditor plan={editor.id?editor:null} account={account} accounts={accounts} onClose={()=>setEditor(null)} onSaved={async result=>{setEditor(null);setDetail(result);await reload();onChanged?.();}}/>}
  </section>;
}
