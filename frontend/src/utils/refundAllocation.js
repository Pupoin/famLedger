// Compare native quotas exactly at the API's four-decimal precision.
function units(value) {
  const text = String(value ?? '').trim();
  if (!/^\d+(?:\.\d{1,4})?$/.test(text)) throw new Error('请输入有效的退款冲抵金额');
  const [whole, fraction = ''] = text.split('.');
  const result = BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'));
  if (result <= 0n) throw new Error('退款冲抵金额必须大于 0');
  return result;
}

function quantity(value) {
  return `${value / 10000n}.${String(value % 10000n).padStart(4, '0')}`;
}

export function buildRefundAllocation(refund, original, originalAmount = '', refundAmount = '') {
  if (!original?.id) throw new Error('请选择原消费');
  if (!refund?.original_currency || !original.original_currency) throw new Error('请先核实交易的原币金额与币种');
  const originalRemaining = units(original.remaining_refundable);
  const refundRemaining = units(refund.refund_info?.remaining_amount ?? refund.original_amount);
  const foreign = original.original_currency !== refund.original_currency;
  if (foreign && (!String(originalAmount).trim() || !String(refundAmount).trim())) {
    throw new Error('跨币种退款需填写双方原币冲抵金额');
  }
  const originalUnits = String(originalAmount).trim() ? units(originalAmount)
    : originalRemaining < refundRemaining ? originalRemaining : refundRemaining;
  const refundUnits = foreign ? units(refundAmount) : originalUnits;
  if (originalUnits > originalRemaining || refundUnits > refundRemaining) {
    throw new Error('分配不能超过退款总额或原消费剩余可退额度');
  }
  return { original_transaction_id: original.id, allocated_amount: quantity(originalUnits),
    original_currency: original.original_currency, refund_original_amount: quantity(refundUnits) };
}
