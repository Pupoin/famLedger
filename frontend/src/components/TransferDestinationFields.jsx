import React from 'react';
import { tx, useLocale } from '../localization';
import AccountSelectDropdown from './AccountSelectDropdown';
import { ArrowRight } from 'lucide-react';

export default function TransferDestinationFields({ transaction, accounts, sourceAccountId, direction,
  onDirectionChange, onSourceChange, destinationId, onDestinationChange, peerAmount, onAmountChange }) {
  useLocale();
  const paired = transaction.paired_transfer;
  const outgoing = paired ? paired.is_outflow : direction === 'outflow';
  const writable = accounts.filter(account => account.is_active !== false && account.can_edit !== false);
  const ownFallback = { id: transaction.account_id, name: transaction.account_name, currency: transaction.currency };
  const peerFallback = paired?.counterpart ? { id: paired.counterpart.account_id,
    name: paired.counterpart.account_name, currency: paired.counterpart.currency, can_edit: false } : null;
  const fromFallback = outgoing ? ownFallback : peerFallback;
  const toFallback = outgoing ? peerFallback : ownFallback;
  const source = accounts.find(account => account.id === sourceAccountId)
    || (fromFallback?.id === sourceAccountId ? fromFallback : null);
  const destination = accounts.find(account => account.id === destinationId)
    || (toFallback?.id === destinationId ? toFallback : null);
  const differentCurrency = source && destination && source.currency !== destination.currency;
  const peerCurrency = outgoing ? destination?.currency : source?.currency;
  const peerId = outgoing ? destinationId : sourceAccountId;
  const oldPeerAccount = paired && accounts.find(account => account.id === paired.counterpart?.account_id);
  const peerReadOnly = Boolean(paired && (!oldPeerAccount || oldPeerAccount.can_edit === false));
  return <div className="space-y-3 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-700">
    {!paired && <label className="block text-xs text-zinc-600 dark:text-zinc-300">{tx('转账方向')}
      <select value={direction} onChange={event => onDirectionChange(event.target.value)} data-testid="edit-transfer-direction"
        className="mt-1 w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100">
        <option value="outflow">{tx('当前账户 → 对方账户')}</option><option value="inflow">{tx('对方账户 → 当前账户')}</option>
      </select>
    </label>}
    <div data-testid="edit-transfer-flow" aria-label={tx('资金流向')} className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2">
      <div className="min-w-0 p-2 rounded-lg border border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-950/30 space-y-1.5">
        <p className="text-xs font-semibold text-blue-600 dark:text-blue-400">{tx('转出账户')}</p>
        <AccountSelectDropdown name="from_account_id" testId="edit-transfer-from-account" value={sourceAccountId}
          accounts={writable.filter(account => account.id !== destinationId)} selectedAccountFallback={fromFallback}
          disabled={!outgoing && peerReadOnly} onChange={event => onSourceChange(event.target.value)}
          wrapLabels placeholder="选择转出账户" emptyLabel={!paired && !outgoing ? '外部账户' : null} />
      </div>
      <ArrowRight aria-hidden="true" className="w-5 h-5 text-zinc-500 justify-self-center rotate-90 sm:rotate-0" />
      <div className="min-w-0 p-2 rounded-lg border border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/30 space-y-1.5">
        <p className="text-xs font-semibold text-emerald-600 dark:text-emerald-400">{tx('转入账户')}</p>
        <AccountSelectDropdown name="to_account_id" testId="edit-transfer-to-account" value={destinationId}
          accounts={writable.filter(account => account.id !== sourceAccountId)} selectedAccountFallback={toFallback}
          disabled={outgoing && peerReadOnly} onChange={event => onDestinationChange(event.target.value)}
          wrapLabels placeholder="选择转入账户" emptyLabel={!paired && outgoing ? '外部账户' : null} />
      </div>
    </div>
    {differentCurrency && <label className="block text-xs text-zinc-600 dark:text-zinc-300">{tx(outgoing ? '实际到账金额' : '实际转出金额')} ({peerCurrency})
      <input type="number" min="0.0001" step="0.0001" required value={peerAmount} disabled={peerReadOnly}
        data-testid="edit-peer-transfer-amount" onChange={event => onAmountChange(event.target.value)}
        className="mt-1 w-full p-2 rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100" />
    </label>}
    {peerId && <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx('保存后同步转账两侧流水与账户余额。')}</p>}
    {peerReadOnly && <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx('没有对端账户的修改权限，不能调整转账账户或金额。')}</p>}
  </div>;
}
