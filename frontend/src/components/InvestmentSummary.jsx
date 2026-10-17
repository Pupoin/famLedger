import React, { lazy, Suspense } from 'react';
import { tx, useLocale } from '../localization';
import { currencySymbol, formatCurrency } from '../utils/currency';
import { formatReturn, returnEstimateNote } from '../utils/investmentReturns';
const InvestmentReturnsChart = lazy(() => import('./InvestmentReturnsChart'));

export default function InvestmentSummary({ data, privacy = false, compact = false, showChart = true, showNotes = true, overview = false, onDrilldown }) {
  useLocale();
  if (!data?.has_accounts) return compact ? null : <p className="text-xs text-zinc-500">{tx('当前尚未录入证券/基金等投资类账户')}</p>;
  const format = value => privacy ? '••••••' : value == null ? tx('待补充')
    : `${formatCurrency(value, data.currency_symbol || currencySymbol(data.currency))} ${data.currency}`;
  const performance = data.performance;
  const initialized = performance?.configured_accounts > 0;
  const periodReturn = initialized ? performance.period?.gain : data.period_return;
  const totalReturn = initialized ? performance.inception?.gain : data.total_return;
  const periodRate = performance?.period?.rates?.mwr;
  const metrics = compact ? [
    ['本期投资回报', periodReturn, true, initialized && performance.period?.estimated], ['市值涨跌', data.period_gain, true], ['分红及利息收入', data.cash_income],
  ] : overview ? [
    ['投资组合价值', data.portfolio_value, false, performance?.period?.closing_estimated],
    ['本期投资回报', periodReturn, true, performance?.period?.estimated],
    ['资金加权期间收益率', periodRate, true, performance?.period?.estimated, true],
  ] : [
    ['投资组合价值', data.portfolio_value, false, initialized && performance.period?.closing_estimated], ['本期投资回报', periodReturn, true, initialized && performance.period?.estimated],
    ['本期投入', data.period_deposit], ['本期提取', data.period_withdrawal],
    ['分红及利息收入', data.cash_income], ['累计已记录回报', totalReturn, true, initialized && performance.inception?.estimated],
  ];
  return <div data-testid="investment-summary" className="space-y-3">
    {compact && <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">{tx('投资参考')}</h2>}
    <div className={`grid grid-cols-2 ${compact || overview ? 'sm:grid-cols-3' : 'md:grid-cols-3 xl:grid-cols-6'} gap-3`}>
      {metrics.map(([label, value, signed, estimated, rate]) => <div key={label} className="min-w-0 rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-800/40 p-3">
        <p className="text-[11px] text-zinc-500">{tx(label)}{estimated && value != null && <span className="ml-1 text-amber-700 dark:text-amber-300">({tx('估算')})</span>}</p>
        <p className={`mt-1 break-words font-mono text-sm font-bold ${signed && value < 0 ? 'text-red-600 dark:text-red-400' : signed && value > 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-zinc-900 dark:text-zinc-100'}`}>
          {rate ? formatReturn(value) : format(value)}
        </p>
      </div>)}
    </div>
    {overview && <div className="space-y-3 rounded-xl border border-zinc-100 p-3 dark:border-zinc-800" data-testid="investment-return-composition">
      <h3 className="text-xs font-semibold text-zinc-800 dark:text-zinc-200">{tx('本期回报构成')}</h3>
      {[
        ['估值盈亏（含汇率影响）', data.composition?.valuation_gain, 'valuation'],
        ['分红及利息收入', data.cash_income, 'income'], ['投资费用', data.cash_cost == null ? null : -data.cash_cost, 'cost'],
      ].map(([name, value, activity]) => <div key={activity} className="flex items-center justify-between gap-3 text-xs">
        {onDrilldown ? <button type="button" onClick={() => onDrilldown(activity)} className="text-left text-blue-600 hover:underline dark:text-blue-400">{tx(name)} ↗</button> : <span className="text-zinc-500">{tx(name)}</span>}
        <span className={`shrink-0 font-mono ${value < 0 ? 'text-red-600 dark:text-red-400' : 'text-zinc-800 dark:text-zinc-200'}`}>{format(value)}</span>
      </div>)}
      <p className="text-[11px] leading-relaxed text-zinc-500">{tx('估值盈亏按本期总回报扣除分红利息、加回投资费用计算，包含汇率及本金基准差异；明细仅列已记录的盈亏。')}</p>
      <details className="border-t border-zinc-100 pt-2 dark:border-zinc-800">
        <summary className="cursor-pointer text-xs font-semibold text-zinc-600 dark:text-zinc-300">{tx('投入与提取')}</summary>
        <div className="mt-2 space-y-2">
          {[['本期投入',data.period_deposit,'deposit'],['本期提取',data.period_withdrawal,'withdrawal']].map(([name,value,activity]) => <div key={activity} className="flex items-center justify-between gap-3 text-xs">
            {onDrilldown ? <button type="button" onClick={() => onDrilldown(activity)} className="text-blue-600 hover:underline dark:text-blue-400">{tx(name)} ↗</button> : <span>{tx(name)}</span>}
            <span className="font-mono text-zinc-800 dark:text-zinc-200">{format(value)}</span>
          </div>)}
          <p className="text-[11px] text-zinc-500">{tx('投入和提取是资金转移，不计入投资回报或消费预算。')}</p>
        </div>
      </details>
      {onDrilldown && <button type="button" onClick={() => onDrilldown('all')} className="text-xs text-blue-600 hover:underline dark:text-blue-400">{tx('查看投资活动')} ↗</button>}
    </div>}
    {!compact && initialized && performance.configured_accounts === performance.account_count && <div className="grid grid-cols-2 gap-2 md:grid-cols-4" data-testid="investment-capital">
      {[['起算市值基准','initial_value'],...(performance.capital?.capital_basis ? [['设定本金基准','capital_basis']] : []),['累计真实投入','contributions'],['累计真实提取','withdrawals'],['起算后净投入','net_contributions']].map(([name,key])=><div className="min-w-0 p-2" key={key}><p className="text-[11px] text-zinc-500">{tx(name)}</p><p className="mt-1 break-words font-mono text-xs font-semibold text-zinc-900 dark:text-zinc-100">{format(performance.capital?.[key])}</p></div>)}
    </div>}
    <div className="space-y-1 text-[11px] leading-relaxed text-zinc-500">
      {performance && performance.configured_accounts < performance.account_count && <p>{tx('已初始化 {p0}/{p1} 个投资账户；请完成全部可见投资账户的设置后计算组合收益率。',{p0:performance.configured_accounts,p1:performance.account_count})}</p>}
      {!initialized && !data.valuation_complete && <p>{tx('本期缺少完整市值记录，请在投资账户的“新建余额”中补充；已记录的分红和利息仍正常统计。')}</p>}
      {data.as_of && <p>{tx('最近市值记录：{p0}', { p0: data.as_of })}</p>}
      {overview && <p>{data.period_start} — {data.period_end}</p>}
      {overview && performance?.period?.estimated && <p className="text-amber-700 dark:text-amber-300">{returnEstimateNote(performance.period)}</p>}
      {showNotes && <p>{tx('投资回报为已记录的市值涨跌加分红利息、减投资费用。市值涨跌不计入消费预算；分红利息按实际收入统计。')}</p>}
      {showNotes && initialized && <p>{tx('起算回报和收益率包含展示币种汇率影响；净投入不等于证券持仓成本，提现可能包含收益。')}</p>}
    </div>
    {showChart && !compact && performance && <Suspense fallback={<p className="text-xs text-zinc-500">{tx('正在加载...')}</p>}><InvestmentReturnsChart data={performance} scope={overview ? 'period' : undefined}/></Suspense>}
  </div>;
}
