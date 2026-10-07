import { describe, expect, it } from 'vitest';
import { initialTransactionSplits, transactionSplitSummary, buildTransactionSplits } from './transactionSplits';

describe('transaction split editing', () => {
  it.each(['expense', 'refund'])('creates two balanced editable rows for %s', transaction_type => {
    const transaction = { amount: '100.0001', transaction_type, narration: 'Order' };
    const rows = initialTransactionSplits(transaction, [{ id: 'food' }, { id: 'shopping' }]);
    expect(rows).toHaveLength(2);
    expect(rows[0].category_id).toBe('food'); expect(rows[1].category_id).toBe('shopping');
    expect(transactionSplitSummary(transaction, rows).balanced).toBe(true);
    expect(buildTransactionSplits(transaction, rows).splits.map(row => row.amount)).toEqual(['50.00', '50.0001']);
  });
  it('keeps existing child categories, notes and four-decimal amounts', () => {
    const transaction = { amount: '1', is_split: true, splits: [
      { id: 'first', amount: '0.0001', category_id: 'food', notes: 'First' },
      { id: 'second', amount: '0.9999', category_id: 'shopping', notes: 'Second' },
    ] };
    const rows = initialTransactionSplits(transaction);
    expect(rows[0].amount).toBe('0.0001'); expect(rows[0].notes).toBe('First');
    expect(buildTransactionSplits(transaction, rows).splits[1].category_id).toBe('shopping');
  });
  it.each(['0', '-1', 'NaN', '1.00001', '30.004'])('rejects invalid or unbalanced split %s', amount => {
    expect(() => buildTransactionSplits({ amount: '100' }, [{ amount }, { amount: '70' }])).toThrow();
  });
});
