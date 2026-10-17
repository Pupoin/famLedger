// P&L is a transaction attribute. Correct the broken category-based Sankey URL
// before fetching, while retaining the selected dates, owner and accounts.
export function normalizeInvestmentFilters(input) {
  const params = new URLSearchParams(input);
  if (params.get('investment_activity') || params.get('funds_flow') || params.get('category_id')) return params;
  const activity = {
    投资盈利: 'gain', 'Investment gains': 'gain',
    投资亏损: 'loss', 'Investment losses': 'loss',
  }[params.get('category_name')?.trim()];
  if (!activity) return params;
  const types = (params.get('transaction_type') || '').split(',').map(value => value.trim()).filter(Boolean);
  const allowed = activity === 'gain' ? ['income'] : ['expense', 'refund'];
  if (types.some(value => !allowed.includes(value))) return params;
  params.set('investment_activity', activity);
  for (const key of ['category_name', 'transaction_type', 'spending_net', 'spending_currency']) params.delete(key);
  return params;
}
