import { describe, expect, it } from 'vitest';
import { budgetTransactionUrl } from './budgetDrilldown';

describe('budget category drilldown', () => {
  it.each([['2024-02', '2024-02-29'], ['2026-02', '2026-02-28'], ['2026-09', '2026-09-30']])('uses the whole selected month %s', (month, end) => {
    const params = new URL(budgetTransactionUrl('餐饮 & Travel', month, 'CNY'), 'http://localhost').searchParams;
    expect(params.get('category_name')).toBe('餐饮 & Travel');
    expect(params.get('start_date')).toBe(`${month}-01`); expect(params.get('end_date')).toBe(end);
    expect(params.get('transaction_type')).toBe('expense,refund');
    expect(params.get('spending_net')).toBe('true'); expect(params.get('spending_currency')).toBe('CNY');
  });
});
