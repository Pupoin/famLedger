import { tx, useLocale } from "../localization.js";
import React from 'react';

export default function BookingMoneyInfo({ transaction, detailed = false, privacy = false }) {
  useLocale();
  if (privacy) return null;
  const t = transaction;
  const foreign = t.original_amount != null && t.original_currency && t.original_currency !== t.currency;
  const converted = t.display_currency && t.display_currency !== t.currency;
  const sourceName = (source) => tx(({ bank: '银行实际结算', manual_confirmation: '人工确认', frankfurter: '交易日历史汇率', same_currency: '同币种' })[source] || source);
  return <div className="text-xs text-zinc-500 space-y-1">
    {t.needs_money_review && <div className="text-amber-700 dark:text-amber-300">{tx("历史原币信息待核对")}</div>}
    {detailed && t.original_amount != null && t.original_currency && (foreign || t.original_currency !== t.display_currency) && <div>{tx("原币")} {t.original_amount} {t.original_currency}</div>}
    {detailed && (foreign || converted) && <div>{tx("固定入账")} {t.amount} {t.currency}{foreign && <>{tx("· 汇率 1")} {t.original_currency} = {t.exchange_rate} {t.currency} · {t.exchange_rate_date} · {sourceName(t.exchange_rate_source)}</>}</div>}
    {detailed && converted && t.display_exchange_rate && <div>{tx("展示换算 1")} {t.display_exchange_rate_base_currency} = {t.display_exchange_rate} {t.display_currency} · {t.display_exchange_rate_date} · {sourceName(t.display_exchange_rate_source)}</div>}
    {detailed && t.display_money_error && <div className="text-amber-700 dark:text-amber-300">{t.display_currency} {tx("金额待换算：")} {tx(t.display_money_error)}</div>}
    {detailed && t.child_book_amount != null && <div>{tx("副卡入账")} {t.child_book_amount} {t.child_book_currency}</div>}
    {detailed && t.master_settlement_amount != null && <div>{tx("主卡固定结算")} {t.master_settlement_amount} {t.master_settlement_currency} · {t.master_exchange_rate_date}</div>}
    {detailed && t.refund_info?.original_total != null && <div>{tx("原币退款进度")} {t.refund_info.total_refunded || t.refund_info.allocated_amount || '0'} / {t.refund_info.original_total} {t.refund_info.currency}</div>}
    {detailed && t.refund_info?.allocations?.map((a, i) => <div key={i}>{tx("冲抵原消费")} {a.allocated_amount} {a.original_currency} {tx("（入账")} {a.original_book_amount} {a.original_book_currency} {tx("），实际到账")} {a.refund_book_amount} {a.refund_book_currency} {tx("，汇兑损益")} {a.fx_difference_amount} {a.fx_difference_currency}</div>)}
  </div>;
}
