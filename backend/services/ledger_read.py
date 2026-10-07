"""Request-local, batched related data for financial reads; never a global cache."""
from sqlmodel import select

from models import Account, Category, RefundAllocation, Transaction, TransactionSplit


class LedgerRead:
    def __init__(self, session):
        self.session = session
        self.transactions, self.accounts, self.allocations, self.splits, self.categories = {}, {}, {}, {}, {}

    def _rows(self, model, column, ids):
        ids = list(set(ids))
        for offset in range(0, len(ids), 900):
            yield from self.session.exec(select(model).where(column.in_(ids[offset:offset + 900]))).all()

    def add_transactions(self, rows):
        self.transactions.update((row.id, row) for row in rows)

    def load_transactions(self, ids):
        self.add_transactions(self._rows(Transaction, Transaction.id, set(ids) - self.transactions.keys()))

    def load_accounts(self, ids):
        self.accounts.update((row.id, row) for row in self._rows(Account, Account.id, set(ids) - self.accounts.keys()))

    def load_splits(self, rows):
        missing = {row.id for row in rows if row.is_split and row.id not in self.splits}
        self.splits.update((key, []) for key in missing)
        for split in self._rows(TransactionSplit, TransactionSplit.transaction_id, missing):
            self.splits[split.transaction_id].append(split)

    def prepare(self, rows):
        rows = list(rows)
        self.add_transactions(rows)
        missing = {row.id for row in rows if row.transaction_type == 'refund' and row.id not in self.allocations}
        self.allocations.update((key, []) for key in missing)
        for allocation in self._rows(RefundAllocation, RefundAllocation.refund_transaction_id, missing):
            self.allocations[allocation.refund_transaction_id].append(allocation)
        original_ids = {link.original_transaction_id for key in missing for link in self.allocations[key]}
        self.load_transactions(original_ids)
        related = rows + [self.transactions[key] for key in original_ids if key in self.transactions]
        self.load_accounts(row.account_id for row in related)
        self.load_splits(related)

    def transaction(self, key):
        if key not in self.transactions:
            self.load_transactions([key])
        return self.transactions.get(key)

    def account(self, key):
        if key not in self.accounts:
            self.load_accounts([key])
        return self.accounts.get(key)

    def transaction_splits(self, row):
        self.load_splits([row])
        return self.splits.get(row.id, [])

    def family_categories(self, family_id):
        if family_id not in self.categories:
            self.categories[family_id] = {row.id: row for row in self.session.exec(
                select(Category).where(Category.family_id == family_id)).all()}
        return self.categories[family_id]
