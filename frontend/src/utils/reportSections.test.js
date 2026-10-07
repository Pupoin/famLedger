import { describe, expect, it } from 'vitest';
import { combineReportSections } from './reportSections';

const current = { history_loaded: false, currency: 'USD', period: 'custom', selected_month: '2026-10',
  date_range: { start: '2026-09-03', end: '2026-10-01' }, kpis: { total_expense: 100 },
  net_worth: { current: 80, trend: [] }, trends: null };
const history = { ...current, history_loaded: true, trends: { monthly_breakdown: [{ expense: 100 }] },
  net_worth: { current: 999, trend: [{ value: 80 }], trend_basis: 'recorded_account_ledger' } };

describe('progressive report sections', () => {
  it('shows current-period figures before historical curves have finished', () => {
    expect(combineReportSections(current, null)).toEqual({ data: current, historyReady: false });
  });
  it('adds matching historical sections without replacing current balances and KPIs', () => {
    const { data, historyReady } = combineReportSections(current, history);
    expect(historyReady).toBe(true);
    expect(data.kpis).toBe(current.kpis);
    expect(data.net_worth.current).toBe(80);
    expect(data.net_worth.trend).toEqual([{ value: 80 }]);
    expect(data.trends).toBe(history.trends);
  });
  it.each([
    { currency: 'CNY' }, { period: 'monthly' }, { selected_month: '2026-09' },
    { date_range: { ...current.date_range, start: '2026-09-01' } },
    { date_range: { ...current.date_range, end: '2026-10-02' } },
  ])('ignores history from a different financial scope: %j', changes => {
    expect(combineReportSections(current, { ...history, ...changes })).toEqual({ data: current, historyReady: false });
  });
  it('can display a complete report without requesting separate history', () => {
    expect(combineReportSections(history, null)).toEqual({ data: history, historyReady: true });
  });
});
