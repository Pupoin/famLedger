import { tx, currentLocale } from '../localization';

export const RETURN_METHODS = [
  ['mwr', '资金加权期间收益率'], ['xirr', '资金加权年化收益率（XIRR）'],
  ['dietz', '期间收益率（Dietz 估算）'], ['twr', '时间加权期间收益率'],
  ['twr_annual', '时间加权年化收益率'], ['simple_annual', '单利年化收益率'],
];
const REASONS = {
  not_initialized: '请先在投资账户的“投资设置”中选择统计起点。',
  baseline_deleted: '起算市值记录已被删除，请重新设置投资统计起点。',
  missing_contributions: '缺少真实投入记录，请补录初始本金或入金。',
  missing_opening_valuation: '缺少可用的期初市值或本金记录，请在投资设置中补充统计依据。',
  missing_closing_valuation: '缺少可用的市值或本金记录，请补充投资统计依据。',
  missing_flow_valuation: '精确时间加权需要资金进出时点的市值；目前可查看资金加权或 Dietz 估算。',
  balance_correction: '期间存在普通余额纠错或缺少本金依据的市值，收益率暂不可计算。',
  before_start: '所选范围早于投资统计起点。', too_short: '请至少记录两个不同日期的市值。',
  under_one_year: '不足一年仅展示期间收益率，不展示年化收益率。',
  zero_base: '缺少有效的投入基数，暂不能计算此收益率。',
  cashflows_require_weighting: '期间有追加或提取，请使用资金加权收益率。',
  multiple_solutions: '现金流存在多个收益率解，无法可靠显示 XIRR；可查看 Dietz 估算。',
  no_solution: '根据当前现金流无法求得有效收益率；可查看 Dietz 估算。',
};
export const returnReason = reason => tx(REASONS[reason] || '暂无可计算的收益率');
export function returnEstimateNote(data) {
  if (!data?.estimated) return '';
  return [
    tx('缺少边界日市值，已按最近记录市值及后续资金活动估算，未记录的市场涨跌未计入。'),
    data.opening_estimated && data.opening_reference_dates?.length && tx('期初参考记录：{p0}', {p0:data.opening_reference_dates.join(', ')}),
    data.closing_estimated && data.closing_reference_dates?.length && tx('期末参考记录：{p0}', {p0:data.closing_reference_dates.join(', ')}),
    (data.opening_from_cashflows || data.closing_from_cashflows) && tx('尚无此前市值，参考值仅来自已记录的本金和资金活动。'),
  ].filter(Boolean).join(' ');
}
export function returnDescription(method) {
  return tx({
    mwr:'根据每笔投入、提取的金额与日期计算，显示该期间的等效资金加权回报。',
    xirr:'等效复利年化收益率；只有一次投入且无提取时，与复合年增长率（CAGR）一致。',
    dietz:'按每笔资金参与投资的时长加权估算；大额资金变动和市场波动可能增加误差。',
    twr:'剔除外部入金、提取的影响，将资金变动前后的投资回报逐段连乘。',
    twr_annual:'将时间加权的累计回报换算成等效复利年化，适用于至少一年的区间。',
    simple_annual:'累计回报除以持有年数，仅用于没有后续追加或提取的投资。',
  }[method] || '暂无可计算的收益率');
}
export function formatReturn(value) {
  return value == null || !Number.isFinite(Number(value)) ? tx('待补充')
    : `${Number(value).toLocaleString(currentLocale(), {minimumFractionDigits:2,maximumFractionDigits:2})}%`;
}
