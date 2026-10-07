// History may finish after a filter/currency change. It must never overwrite
// current balances or attach a curve from a different financial scope.
export function combineReportSections(current, history) {
  if (!current) return { data: null, historyReady: false };
  if (current.history_loaded) return { data: current, historyReady: true };
  const historyReady = !!history?.history_loaded && history.currency === current.currency
    && history.period === current.period && history.selected_month === current.selected_month
    && history.date_range?.start === current.date_range?.start
    && history.date_range?.end === current.date_range?.end;
  if (!historyReady) return { data: current, historyReady: false };
  return { historyReady: true, data: { ...current, trends: history.trends,
    net_worth: { ...current.net_worth, trend: history.net_worth.trend,
      trend_basis: history.net_worth.trend_basis, trend_label: history.net_worth.trend_label } } };
}
