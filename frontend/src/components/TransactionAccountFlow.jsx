import React from 'react';
import { Users } from 'lucide-react';
import { tx, useLocale } from '../localization';

const ownLabels = new Set(['我的', '本人']);

function AccountNode({ name, isOwner, ownerName, secondary, side }) {
  if (!name || name === '外部账户' || name === '私有账户') {
    return <span data-testid={`transfer-${side}-account`} className="text-zinc-400">{tx(name || '外部账户')}</span>;
  }
  const shared = isOwner === false || (isOwner == null && Boolean(ownerName));
  return <span data-testid={`transfer-${side}-account`} className="inline-flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5">
    {shared && <span data-testid="transfer-account-owner" title={tx('由 {p0} 共享', { p0: ownerName || tx('共享成员') })}
      className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 font-medium">
      <Users aria-hidden="true" className="w-2.5 h-2.5 shrink-0" />
      <span className="break-words">{ownerName || tx('共享成员')}</span>
      <span className="font-normal text-zinc-400 dark:text-zinc-500">·</span>
    </span>}
    <span className={`break-words ${secondary ? 'text-zinc-500 dark:text-zinc-400' : ''}`}>{name}</span>
  </span>;
}

export default function TransactionAccountFlow({ transaction, fallbackAccount }) {
  useLocale();
  const sameAccount = fallbackAccount && (!transaction.account_id || transaction.account_id === fallbackAccount.id);
  const legacyOwner = !ownLabels.has(transaction.account_owner) ? transaction.account_owner : null;
  const primary = {
    name: transaction.account_name || (sameAccount && fallbackAccount.name) || tx('银行账户'),
    isOwner: typeof transaction.account_is_owner === 'boolean' ? transaction.account_is_owner
      : sameAccount && typeof fallbackAccount.is_owner === 'boolean' ? fallbackAccount.is_owner : undefined,
    ownerName: transaction.account_owner_name || legacyOwner || (sameAccount && fallbackAccount.owner) || null,
  };
  const identified = transaction.transfer_counterparty;
  const peer = {
    name: transaction.transfer_peer_account || identified?.account_name,
    isOwner: typeof transaction.transfer_peer_is_owner === 'boolean' ? transaction.transfer_peer_is_owner : identified?.is_owner,
    ownerName: transaction.transfer_peer_owner_name || identified?.owner_name,
  };
  const direction = transaction.funds_direction || transaction.extra?.direction;
  const outgoing = typeof transaction.transfer_is_outflow === 'boolean' ? transaction.transfer_is_outflow
    : ['out', 'outflow'].includes(direction) ? true
    : ['in', 'inflow'].includes(direction) ? false
    : !/(转入|收到)/.test(transaction.narration || '');
  return <span data-testid="transfer-account-flow" className="font-semibold text-blue-600 dark:text-blue-400 flex min-w-0 items-center flex-wrap gap-x-1 gap-y-0.5 leading-tight">
    <AccountNode {...(outgoing ? primary : peer)} secondary side="source" />
    <span aria-hidden="true" className="text-blue-500 font-bold shrink-0">➔</span>
    <AccountNode {...(outgoing ? peer : primary)} side="destination" />
    {identified && !transaction.transfer_id && !transaction.paired_transfer &&
      <span data-testid="transfer-unpaired-label" className="font-normal text-zinc-400 dark:text-zinc-500">({tx('未配对')})</span>}
  </span>;
}
