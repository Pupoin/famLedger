// Explicit ledger direction takes precedence over legacy title/notes hints.
export function isAdjustmentDecrease(transaction) {
  const direction = transaction.extra?.direction;
  if (direction === 'increase' || direction === 'decrease') return direction === 'decrease';
  return transaction.funds_direction === 'outflow' || (transaction.narration || '').includes('(-')
    || (transaction.notes || '').includes('减少');
}
