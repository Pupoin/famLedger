const formatters = new Map();

// Cache formatting machinery only; no monetary values are retained.
function moneyFormatter(locale) {
  if (!formatters.has(locale)) {
    if (formatters.size >= 16) formatters.clear();
    formatters.set(locale, new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  }
  return formatters.get(locale);
}

// Mask monetary text at render time, including tooltips and accessible labels.
export function chartMoney(value, symbol, privacyMode, locale, options = {}) {
  if (privacyMode) return '••••••';
  const number = Number(value || 0);
  if (options.compact) return `${symbol}${number >= 1000 ? `${(number / 1000).toFixed(1)}k` : number}`;
  return `${symbol}${moneyFormatter(locale).format(number)}`;
}
