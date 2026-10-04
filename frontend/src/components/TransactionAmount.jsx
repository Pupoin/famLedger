import { tx, useLocale, currentLocale } from "../localization.js";
import React from 'react';
import { currencySymbol, originalTransactionMoney } from '../utils/currency';

export default function TransactionAmount({ transaction, detailed = false, privacy = false }) {
  useLocale();
  const t = transaction;
  const money = detailed ? { amount: t.display_amount, currency: t.display_currency } : originalTransactionMoney(t);
  if (privacy) return <>••••••</>;
  if (money.amount == null) return <>{tx("待换算")} {money.currency}</>;
  const sign = t.transaction_type === 'transfer' ? ''
    : t.transaction_type === 'income' || t.transaction_type === 'refund' ? '+'
    : t.transaction_type === 'adjustment' ? (t.funds_direction === 'outflow' || (t.narration || '').includes('(-') || (t.notes || '').includes('减少') ? '-' : '+')
    : '-';
  return <>{sign}{currencySymbol(money.currency)}{Math.abs(Number(money.amount)).toLocaleString(currentLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })} <span className="text-xs font-semibold">{money.currency}</span></>;
}
