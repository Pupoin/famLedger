export const transferSourceAccounts = accounts => accounts.filter(account =>
  account.is_active !== false && !account.relationship_only && account.can_edit !== false);

export const transferDestinationAccounts = (accounts, sourceId) => accounts.filter(account =>
  account.id !== sourceId && account.is_active !== false && !account.relationship_only
  && (account.can_receive_transfer === true || account.can_edit !== false));
