import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Calendar, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { tx, useLocale } from '../localization';
import { useDateFormat } from '../DateFormatContext';

const isoDate = (year, month, day) => `${String(year).padStart(4,'0')}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
const calendarDate = (year, month, day) => {
  const date = new Date();
  date.setFullYear(year, month, day);
  date.setHours(12,0,0,0);
  return date;
};
const buttonClass = 'rounded-lg p-2 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-30';

// Render the picker in the page rather than relying on native date-input
// segments, which can receive touch focus without opening a calendar.
export default function CalendarDateInput({value='', onChange, label='选择日期', className='', min, max, disabled=false, name, ...props}) {
  const locale = useLocale();
  const { formatDate } = useDateFormat();
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState(()=>({year:new Date().getFullYear(),month:new Date().getMonth()}));
  const trigger = useRef(null);
  const dialog = useRef(null);
  const id = useId();
  const todayDate = new Date();
  const today = isoDate(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate());
  const allowed = day => (!min || day>=min) && (!max || day<=max);
  const openCalendar = () => {
    const initial = value || (min && today<min ? min : max && today>max ? max : today);
    const [year, m] = initial.split('-').map(Number);
    setMonth({year,month:m-1});
    setOpen(true);
  };
  const select = day => {
    onChange?.({target:{value:day,name}});
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (dialog.current?.querySelector('[aria-pressed="true"]:not(:disabled)') || dialog.current?.querySelector('button:not(:disabled)'))?.focus();
    const handleKey = event => {
      if (event.key==='Escape') {
        event.preventDefault();event.stopPropagation();setOpen(false);
      }
      if (event.key==='Tab') {
        const controls = [...dialog.current.querySelectorAll('button:not(:disabled),select:not(:disabled)')];
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && document.activeElement===first) {event.preventDefault();last?.focus();}
        else if (!event.shiftKey && document.activeElement===last) {event.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',handleKey,true);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown',handleKey,true);
      trigger.current?.focus();
    };
  },[open]);

  const first = calendarDate(month.year,month.month,1);
  const offset = (first.getDay()+6)%7;
  const days = calendarDate(month.year,month.month+1,0).getDate();
  const years = Array.from({length:Math.max(2100,month.year)-Math.min(1900,month.year)+1},(_,i)=>Math.min(1900,month.year)+i);
  const monthLabels = Array.from({length:12},(_,i)=>new Intl.DateTimeFormat(locale,{month:'long'}).format(new Date(2024,i,1)));
  const weekLabels = Array.from({length:7},(_,i)=>new Intl.DateTimeFormat(locale,{weekday:'short'}).format(new Date(2024,0,1+i)));
  const navigate = delta => {
    const next = calendarDate(month.year,month.month+delta,1);
    setMonth({year:next.getFullYear(),month:next.getMonth()});
  };

  return <>
    <button {...props} ref={trigger} type="button" disabled={disabled} onClick={openCalendar}
      aria-label={tx(label)} aria-haspopup="dialog" aria-expanded={open} aria-controls={open?id:undefined}
      className={`inline-flex min-w-0 items-center justify-between gap-1.5 text-left cursor-pointer ${className}`}>
      <span className="truncate">{value?formatDate(value):tx('选择日期')}</span><Calendar aria-hidden="true" className="w-3.5 h-3.5 shrink-0"/>
    </button>
    {name&&<input type="hidden" name={name} value={value}/>}
    {open&&createPortal(<div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/40 p-3" onClick={e=>{if(e.target===e.currentTarget)setOpen(false);}}>
      <section id={id} ref={dialog} role="dialog" aria-modal="true" aria-label={tx(label)} data-testid="date-picker"
        className="w-full max-w-sm max-h-[90dvh] overflow-y-auto rounded-2xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-4 shadow-xl text-zinc-900 dark:text-zinc-100">
        <header className="flex items-center justify-between mb-3"><h3 className="font-semibold text-sm">{tx(label)}</h3>
          <button type="button" className={buttonClass} aria-label={tx('关闭')} onClick={()=>setOpen(false)}><X className="w-4 h-4"/></button>
        </header>
        <div className="flex items-center gap-2 mb-3">
          <button type="button" className={buttonClass} aria-label={tx('上一月')} disabled={month.year<=1&&month.month===0} onClick={()=>navigate(-1)}><ChevronLeft className="w-4 h-4"/></button>
          <select aria-label={tx('年份')} className="min-w-0 flex-1 bg-transparent rounded-lg p-2 text-sm" value={month.year} onChange={e=>setMonth({...month,year:Number(e.target.value)})}>
            {years.map(year=><option key={year} value={year}>{year}</option>)}
          </select>
          <select aria-label={tx('月份')} className="min-w-0 flex-1 bg-transparent rounded-lg p-2 text-sm" value={month.month} onChange={e=>setMonth({...month,month:Number(e.target.value)})}>
            {monthLabels.map((label,i)=><option key={i} value={i}>{label}</option>)}
          </select>
          <button type="button" className={buttonClass} aria-label={tx('下一月')} disabled={month.year>=9999&&month.month===11} onClick={()=>navigate(1)}><ChevronRight className="w-4 h-4"/></button>
        </div>
        <div className="grid grid-cols-7 gap-1 text-center">
          {weekLabels.map(label=><span key={label} className="text-xs text-zinc-500 py-1">{label}</span>)}
          {Array.from({length:offset},(_,i)=><span key={`blank-${i}`}/>)}
          {Array.from({length:days},(_,i)=>{
            const day=isoDate(month.year,month.month,i+1),selected=day===value;
            return <button key={day} type="button" data-date={day} aria-label={day} aria-pressed={selected}
              aria-current={day===today?'date':undefined} disabled={!allowed(day)} onClick={()=>select(day)}
              className={`min-h-10 rounded-lg text-sm disabled:opacity-25 ${selected?'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900':'hover:bg-zinc-100 dark:hover:bg-zinc-800'} ${day===today&&!selected?'ring-1 ring-inset ring-zinc-300 dark:ring-zinc-600':''}`}>
              {i+1}
            </button>;
          })}
        </div>
        <footer className="flex justify-between mt-3 border-t border-zinc-200 dark:border-zinc-800 pt-2 text-sm">
          <button type="button" className={buttonClass} onClick={()=>select('')}>{tx('清空')}</button>
          <button type="button" className={buttonClass} disabled={!allowed(today)} onClick={()=>select(today)}>{tx('今日')}</button>
        </footer>
      </section>
    </div>,document.body)}
  </>;
}
