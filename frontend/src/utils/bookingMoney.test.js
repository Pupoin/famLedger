import { describe, it, expect } from 'vitest';
import { currencySymbol, totalsByCurrency, formatCurrencyTotals } from './currency';

describe('account booking currency display', () => {
  it('keeps native account currencies separate in list totals', () => {
    const result = totalsByCurrency([{amount: 700, currency: 'CNY', transaction_type: 'expense'},
      {amount: 100, currency: 'USD', transaction_type: 'expense'}], 'expense');
    expect(result).toEqual({CNY: 700, USD: 100});
    expect(formatCurrencyTotals(result)).toBe('¥700.00 CNY / $100.00 USD');
  });
  it('does not show refunds as wages', () => {
    expect(totalsByCurrency([{amount:720, currency:'CNY', transaction_type:'refund'}], 'income')).toEqual({});
  });
  it('aggregates the original currencies shown in activity rows separately', () => {
    expect(totalsByCurrency([
      {amount:700, currency:'CNY', original_amount:100, original_currency:'USD', transaction_type:'expense'},
      {amount:700, currency:'CNY', original_amount:90, original_currency:'EUR', transaction_type:'expense'},
      {amount:720, currency:'CNY', original_amount:100, original_currency:'USD', transaction_type:'refund'},
    ], 'net', 'original')).toEqual({USD:0, EUR:-90});
  });
  it('shows actual refund cash in the daily balance change', () => {
    expect(totalsByCurrency([{amount:700, currency:'CNY', transaction_type:'expense'},
      {amount:720, currency:'CNY', transaction_type:'refund'}])).toEqual({CNY:20});
    expect(currencySymbol('USD')).toBe('$');
  });
});
