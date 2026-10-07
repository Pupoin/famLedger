export function budgetTransactionUrl(categoryName, month, currency) {
  const [year, number] = month.split('-').map(Number);
  const lastDay = new Date(year, number, 0).getDate();
  const params = new URLSearchParams({
    category_name: categoryName,
    start_date: `${month}-01`,
    end_date: `${month}-${lastDay}`,
    transaction_type: 'expense,refund',
    spending_net: 'true',
  });
  if (currency) params.set('spending_currency', currency);
  return `/transactions?${params}`;
}
