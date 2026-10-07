function units(value) {
  const text = String(value ?? '').trim();
  if (!/^\d+(?:\.\d{1,4})?$/.test(text)) throw new Error('拆分金额必须为有效正数');
  const [whole, fraction = ''] = text.split('.');
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'));
}

export function splitMoney(value) {
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const fraction = String(absolute % 10000n).padStart(4, '0').replace(/0+$/, '').padEnd(2, '0');
  return `${negative ? '-' : ''}${absolute / 10000n}.${fraction}`;
}

export function initialTransactionSplits(transaction, categories = []) {
  if (!transaction) return [];
  if (transaction.is_split && transaction.splits?.length >= 2) return transaction.splits.map((row, index) => ({
    id: row.id || `split-${index}`, category_id: row.category_id || '',
    amount: splitMoney(units(row.amount)), notes: row.notes || '',
  }));
  const total = units(transaction.amount);
  const half = total / 2n;
  return [
    { id: 'split-1', category_id: transaction.category_id || categories[0]?.id || '', amount: splitMoney(half), notes: transaction.narration || '' },
    { id: 'split-2', category_id: categories[1]?.id || categories[0]?.id || '', amount: splitMoney(total - half), notes: '' },
  ];
}

export function transactionSplitSummary(transaction, splits) {
  const total = units(transaction.amount);
  let allocated = 0n;
  let valid = splits.length >= 2;
  for (const row of splits) {
    try { const amount = units(row.amount); valid = valid && amount > 0n; allocated += amount; }
    catch { valid = false; }
  }
  return { total, remaining: total - allocated, balanced: valid && total === allocated };
}

export function buildTransactionSplits(transaction, splits) {
  if (!transactionSplitSummary(transaction, splits).balanced) throw new Error('拆分金额必须为正数，且总和等于交易入账金额');
  return { splits: splits.map(row => ({ category_id: row.category_id || null,
    amount: splitMoney(units(row.amount)), notes: row.notes?.trim() || null })) };
}
