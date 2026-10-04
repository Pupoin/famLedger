// Mask monetary text at render time, including tooltips and accessible labels.
export function chartMoney(value, symbol, privacyMode, locale, options = {}) {
  if (privacyMode) return '••••••';
  const number = Number(value || 0);
  if (options.compact) return `${symbol}${number >= 1000 ? `${(number / 1000).toFixed(1)}k` : number}`;
  return `${symbol}${number.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
