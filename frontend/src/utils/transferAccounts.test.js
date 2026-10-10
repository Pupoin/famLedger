import { describe, expect, it } from 'vitest';
import { transferSourceAccounts, transferDestinationAccounts } from './transferAccounts';

const accounts = [
  { id: 'own', can_edit: true, can_receive_transfer: true },
  { id: 'shared', can_edit: false, can_receive_transfer: true },
  { id: 'denied', can_edit: false, can_receive_transfer: false },
  { id: 'inactive', can_edit: true, can_receive_transfer: true, is_active: false },
  { id: 'private-primary', can_edit: true, can_receive_transfer: true, relationship_only: true },
];

describe('transfer account permissions', () => {
  it('keeps readonly, unavailable and relationship-only accounts out of source choices', () => {
    expect(transferSourceAccounts(accounts).map(account => account.id)).toEqual(['own']);
  });
  it('offers only active accessible destinations other than the source', () => {
    expect(transferDestinationAccounts(accounts, 'own').map(account => account.id)).toEqual(['shared']);
  });
});
