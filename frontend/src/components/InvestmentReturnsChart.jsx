import React from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine } from 'recharts';
import { tx, useLocale } from '../localization';
import { useTheme } from '../ThemeContext';
import { usePageViewState } from '../PageViewContext';
import { RETURN_METHODS, formatReturn, returnReason, returnDescription, returnEstimateNote } from '../utils/investmentReturns';

export default function InvestmentReturnsChart({ data, embedded = false, scope: controlledScope, children }) {
  useLocale();
  const { theme } = useTheme() || {};
  const [method, setMethod] = usePageViewState('investment-rate-method', 'mwr');
  const [savedScope, setScope] = usePageViewState('investment-rate-scope', 'period');
  const scope = controlledScope ?? savedScope;
  const selected = data?.[scope];
  const estimated = selected?.estimated && selected?.rates?.[method] != null;
  const points = (data?.[scope === 'period' ? 'period_series' : 'inception_series'] || [])
    .map(point => ({...point,timestamp:Date.parse(`${point.date}T00:00:00Z`)}));
  const hasValues = points.some(point => point[method] != null && Number.isFinite(point[method]));
  const crossesYear = points.length > 1 && points[0].date.slice(0,4) !== points[points.length-1].date.slice(0,4);
  const label = tx(RETURN_METHODS.find(([key]) => key === method)?.[1]);
  const description = <p className="text-[11px] leading-relaxed text-zinc-500">{returnDescription(method)}</p>;
  const valuationNotes = <p className="text-[11px] leading-relaxed text-zinc-500">{tx('曲线基于已记录市值，不补造缺失估值。期间收益率从对应起点累计，包含展示币种的汇率影响。Dietz 为估算；复利年化不代表自动再投资。')}</p>;
  const dropdown = 'w-full sm:w-auto max-w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-2 text-xs text-zinc-700 dark:text-zinc-200';
  return <div data-testid="investment-returns-chart" className={`min-w-0 space-y-3 ${embedded ? '' : 'border-t border-zinc-200/70 dark:border-zinc-800 pt-4'}`}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-zinc-900 dark:text-white">{tx('投资收益率走势')}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <p className={`font-mono text-xl font-bold ${selected?.rates?.[method] < 0 ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'}`} data-testid="investment-selected-return">{formatReturn(selected?.rates?.[method])}</p>
          {estimated && <span data-testid="investment-return-estimated" className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">{tx('估算')}</span>}
        </div>
      </div>
      <div className="grid w-full grid-cols-1 gap-2 sm:w-auto sm:flex sm:flex-wrap">
        {controlledScope == null && <select aria-label={tx('收益率统计范围')} data-testid="investment-return-scope" value={scope} onChange={event => setScope(event.target.value)} className={dropdown}>
          <option value="period">{tx('所选期间')}</option><option value="inception">{tx('起算以来')}</option>
        </select>}
        <select aria-label={tx('收益率计算方法')} data-testid="investment-return-method" value={method} onChange={event => setMethod(event.target.value)} className={dropdown}>
          {RETURN_METHODS.map(([key,name]) => <option key={key} value={key}>{tx(name)}</option>)}
        </select>
      </div>
    </div>
    <p className="text-[11px] text-zinc-500">{selected?.start} — {selected?.end} · {label}</p>
    {!embedded && description}
    {estimated && <p data-testid="investment-return-estimate-note" className="text-xs leading-relaxed text-amber-700 dark:text-amber-300">{returnEstimateNote(selected)}</p>}
    {selected?.reasons?.[method] && <p role="status" className="text-xs leading-relaxed text-amber-700 dark:text-amber-300">{returnReason(selected.reasons[method])}</p>}
    {hasValues ? <div className="h-52 w-full min-w-0" aria-label={tx('投资收益率走势')}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{top:12,right:26,left:4,bottom:0}}>
          <XAxis type="number" scale="time" dataKey="timestamp" domain={['dataMin','dataMax']} tickLine={false} axisLine={false}
            tickFormatter={value => new Date(value).toISOString().slice(crossesYear ? 0 : 5,crossesYear ? 7 : 10)} tick={{fontSize:11,fill:'#71717a'}} minTickGap={30}/>
          <YAxis width={58} tickLine={false} axisLine={false} tickFormatter={value => `${Number(value.toFixed(1))}%`} tick={{fontSize:10,fill:'#71717a'}}/>
          <ReferenceLine y={0} stroke={theme === 'dark' ? '#52525b' : '#d4d4d8'} strokeDasharray="3 3"/>
          <Tooltip formatter={(value, name, item) => [`${item.payload?.estimated ? '≈ ' : ''}${formatReturn(value)}`,label]} labelFormatter={value => new Date(value).toISOString().slice(0,10)}
            contentStyle={{backgroundColor:theme === 'dark' ? '#18181b' : '#fff',borderColor:theme === 'dark' ? '#3f3f46' : '#e4e4e7',borderRadius:8,fontSize:11}}/>
          <Line type="linear" dataKey={method} stroke="#6366f1" strokeWidth={2} dot={{r:2}} connectNulls={false} isAnimationActive={false}/>
        </LineChart>
      </ResponsiveContainer>
    </div> : <div className="flex h-28 items-center justify-center rounded-lg bg-zinc-50 dark:bg-zinc-800/30 p-4 text-center text-xs text-zinc-500">{tx('暂无可计算的收益率')}</div>}
    {embedded ? <details data-testid="investment-calculation-notes" className="border-t border-zinc-200/70 pt-3 dark:border-zinc-800">
      <summary className="cursor-pointer text-xs font-semibold text-zinc-600 dark:text-zinc-300">{tx('计算说明')}</summary>
      <div className="mt-2 space-y-2 text-[11px] leading-relaxed text-zinc-500">{description}{valuationNotes}{children}</div>
    </details> : valuationNotes}
  </div>;
}
