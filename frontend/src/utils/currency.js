const NUMBER_FORMATTER = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Format an amount with a currency symbol: thousands separators, and the
 * sign placed before the symbol for negatives (e.g. "-$12.00", not "$-12.00").
 */
export function formatCurrency(amount, symbol) {
  const num = Number(amount) || 0;
  const sign = num < 0 ? "-" : "";
  return `${sign}${symbol}${NUMBER_FORMATTER.format(Math.abs(num))}`;
}

export function currencySymbol(code) {
  return ({ CNY: '¥', USD: '$', EUR: '€', GBP: '£', CAD: 'C$', AUD: 'A$', INR: '₹', JPY: '¥', CHF: 'CHF ', SGD: 'S$', HKD: 'HK$' })[code] || `${code || ''} `;
}

// Old rows without verified original money retain their known booking amount.
export function originalTransactionMoney(transaction) {
  if (transaction.original_amount != null && transaction.original_currency) {
    return { amount: transaction.original_amount, currency: transaction.original_currency };
  }
  return {
    amount: transaction.child_book_amount ?? transaction.amount,
    currency: transaction.child_book_currency || transaction.currency,
  };
}

export function totalsByCurrency(transactions, direction = 'net', basis = 'booking') {
  const totals = {};
  for (const t of transactions) {
    const money = basis === 'original' ? originalTransactionMoney(t) : t;
    const value = Math.abs(Number(money.amount) || 0);
    const code = money.currency || 'CNY';
    let amount = 0;
    if (direction === 'income' && t.transaction_type === 'income') amount = value;
    if (direction === 'expense' && t.transaction_type === 'expense') amount = value;
    if (direction === 'net') {
      if (t.transaction_type === 'expense') amount = -value;
      if (t.transaction_type === 'income' || t.transaction_type === 'refund') amount = value;
    }
    if (amount) totals[code] = (totals[code] || 0) + amount;
  }
  return totals;
}

export function formatCurrencyTotals(totals) {
  return Object.entries(totals).map(([code, value]) => `${formatCurrency(value, currencySymbol(code))} ${code}`).join(' / ') || '0.00';
}
