import React from 'react';
import { tx, useLocale } from '../localization';
import { normalizeAccountTypeKey } from '../utils/accountTypes';
import { formatReturn, returnReason, returnEstimateNote } from '../utils/investmentReturns';

export default function AccountInvestmentReturn({ account, group = false }) {
  useLocale();
  if (normalizeAccountTypeKey(account) !== 'investment') return null;
  const data = account.investment_ytd;
  const valid = data?.rate != null && Number.isFinite(Number(data.rate));
  const value = valid ? Number(Number(data.rate).toFixed(2)) || 0 : null;
  const text = value == null ? '—' : `${data.estimated ? '≈ ' : ''}${value > 0 ? '+' : ''}${formatReturn(value)}`;
  const reason = !data ? tx('正在加载...') : data.reason === 'load_failed'
    ? tx('今年收益率暂时无法加载') : value == null ? returnReason(data.reason) : tx('资金加权期间收益率');
  const title = [tx('今年投资收益率：{p0}', { p0: text }), reason,
    data?.as_of && tx('截至 {p0}', { p0: data.as_of }), valid && returnEstimateNote(data), data?.currency].filter(Boolean).join(' · ');
  return <span data-testid={group ? 'investment-group-ytd-return' : 'account-ytd-return'} title={title}
    className={`mt-0.5 block truncate font-mono ${group ? 'text-[11px]' : 'text-[10px]'} font-medium ${value > 0
      ? 'text-emerald-600 dark:text-emerald-400' : value < 0
        ? 'text-red-600 dark:text-red-400' : 'text-zinc-500 dark:text-zinc-400'}`}>
    {tx('今年 {p0}', { p0: text })}
  </span>;
}
