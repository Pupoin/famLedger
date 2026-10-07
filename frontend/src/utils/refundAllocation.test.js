import { describe, expect, it } from 'vitest';
import { buildRefundAllocation } from './refundAllocation';

const refund = { original_amount: '100', original_currency: 'CNY', refund_info: { remaining_amount: '70' } };
const original = { id: 'purchase', remaining_refundable: '30', original_currency: 'CNY' };

describe('refund allocation requests', () => {
  it('uses the remaining refund quota and the original purchase quota for a partial match', () => {
    expect(buildRefundAllocation(refund, original)).toEqual({ original_transaction_id: 'purchase', allocated_amount: '30.0000',
      original_currency: 'CNY', refund_original_amount: '30.0000' });
    expect(buildRefundAllocation(refund, original, '10.0012').allocated_amount).toBe('10.0012');
  });
  it('requires both native quantities for a cross-currency allocation', () => {
    const foreign = { ...original, original_currency: 'USD' };
    expect(() => buildRefundAllocation(refund, foreign, '10')).toThrow('双方原币');
    expect(buildRefundAllocation(refund, foreign, '10', '70').refund_original_amount).toBe('70.0000');
  });
  it.each(['0', '-1', 'NaN', 'Infinity', '1.00001', '31'])('rejects invalid or over-limit original quantity %s', amount => {
    expect(() => buildRefundAllocation(refund, original, amount)).toThrow();
  });
  it('rejects an amount above the remaining refund even if the original has enough quota', () => {
    expect(() => buildRefundAllocation(refund, { ...original, remaining_refundable: '200' }, '71')).toThrow('剩余可退额度');
  });
  it('preserves four-decimal quotas near the ledger maximum without float rounding', () => {
    expect(buildRefundAllocation({ original_amount: '99999999999999.9999', original_currency: 'CNY' },
      { ...original, remaining_refundable: '99999999999999.9998' }).allocated_amount).toBe('99999999999999.9998');
  });
});
