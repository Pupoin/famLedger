export function allocateBudgetAmounts(totalBudget, percentages) {
  const cents = Math.round((Number(totalBudget) + Number.EPSILON) * 100);
  const entries = Object.entries(percentages).map(([name, value], index) => {
    const units = Math.round(Number(value || 0) * 100);
    const raw = cents * units / 10000;
    return { name, index, amount: Math.floor(raw), remainder: raw - Math.floor(raw), raw };
  });
  const target = Math.round(entries.reduce((sum, entry) => sum + entry.raw, 0));
  const extras = target - entries.reduce((sum, entry) => sum + entry.amount, 0);
  const order = [...entries].sort((a, b) => b.remainder - a.remainder || a.index - b.index);
  for (const entry of order.slice(0, extras)) entry.amount += 1;
  return Object.fromEntries(entries.map(entry => [entry.name, entry.amount / 100]));
}
