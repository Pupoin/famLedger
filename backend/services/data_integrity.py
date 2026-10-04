"""Validate both physical foreign keys and financial tenant relationships."""
def sqlite_integrity_problems(connection):
    problems = []
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        return ["SQLite integrity_check failed"]
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        problems.append("Dangling foreign key")
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    from sqlmodel import SQLModel
    import models  # register the expected foreign keys, even if an archive omitted them
    for table in SQLModel.metadata.tables.values():
        if table.name not in tables:
            continue
        source_columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table.name}")')}
        for foreign_key in table.foreign_keys:
            source = foreign_key.parent.name
            target = foreign_key.column
            if source not in source_columns:
                continue
            if target.table.name not in tables:
                if connection.execute(f'SELECT 1 FROM "{table.name}" WHERE "{source}" IS NOT NULL LIMIT 1').fetchone():
                    problems.append(f"Missing referenced table: {target.table.name}")
                continue
            sql = (f'SELECT 1 FROM "{table.name}" s LEFT JOIN "{target.table.name}" t '
                   f'ON s."{source}"=t."{target.name}" WHERE s."{source}" IS NOT NULL '
                   f'AND t."{target.name}" IS NULL LIMIT 1')
            if connection.execute(sql).fetchone():
                problems.append(f"Dangling reference: {table.name}.{source}")
    columns = {table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
               for table in tables if table in {
                   "accounts", "users", "categories", "transactions", "transaction_splits",
                   "transfers", "refund_allocations", "account_shares", "personal_debts", "pending_fx_transactions"}}

    def check(requirements, sql, reason):
        if all(set(fields) <= columns.get(table, set()) for table, fields in requirements.items()):
            if connection.execute(sql).fetchone():
                problems.append(reason)

    check({"accounts": ["owner_id", "family_id"], "users": ["id", "family_id"]},
          "SELECT 1 FROM accounts a LEFT JOIN users u ON u.id=a.owner_id WHERE a.owner_id IS NOT NULL AND (u.id IS NULL OR a.family_id IS NOT u.family_id) LIMIT 1",
          "Account owner belongs to another family")
    check({"accounts": ["id", "parent_account_id", "family_id"]},
          "SELECT 1 FROM accounts a LEFT JOIN accounts p ON p.id=a.parent_account_id WHERE a.parent_account_id IS NOT NULL AND (p.id IS NULL OR p.family_id IS NOT a.family_id OR a.id=p.id) LIMIT 1",
          "Invalid primary-card relation")
    check({"categories": ["id", "parent_id", "family_id"]},
          "SELECT 1 FROM categories c LEFT JOIN categories p ON p.id=c.parent_id WHERE c.parent_id IS NOT NULL AND (p.id IS NULL OR p.family_id IS NOT c.family_id OR c.id=p.id) LIMIT 1",
          "Invalid category parent")
    check({"transactions": ["account_id", "category_id"], "accounts": ["id", "family_id"], "categories": ["id", "family_id"]},
          "SELECT 1 FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id WHERE t.category_id IS NOT NULL AND (c.id IS NULL OR c.family_id IS NOT a.family_id) LIMIT 1",
          "Transaction category belongs to another family")
    # Paired legs may settle in different account currencies. Compare their
    # shared original amount when the booked amounts cannot be compared.
    check({"transfers": ["family_id", "outflow_transaction_id", "inflow_transaction_id"], "transactions": ["id", "account_id", "amount", "currency", "original_amount", "original_currency"], "accounts": ["id", "family_id"]},
          "SELECT 1 FROM transfers r LEFT JOIN transactions o ON o.id=r.outflow_transaction_id LEFT JOIN transactions i ON i.id=r.inflow_transaction_id LEFT JOIN accounts a ON a.id=o.account_id LEFT JOIN accounts b ON b.id=i.account_id WHERE o.id IS NULL OR i.id IS NULL OR o.id=i.id OR a.family_id IS NOT r.family_id OR b.family_id IS NOT r.family_id OR NOT ((o.currency=i.currency AND ABS(o.amount-i.amount)<=0.00001) OR (o.original_currency IS NOT NULL AND i.original_currency IS NOT NULL AND o.original_currency=i.original_currency AND o.original_amount IS NOT NULL AND i.original_amount IS NOT NULL AND o.original_amount>0 AND i.original_amount>0 AND ABS(o.original_amount-i.original_amount)<=0.00001)) LIMIT 1",
          "Invalid transfer family, currency or amount")
    check({"transfers": ["amount", "outflow_transaction_id"], "transactions": ["id", "amount"]},
          "SELECT 1 FROM transfers r JOIN transactions t ON t.id=r.outflow_transaction_id WHERE r.amount<=0 OR ABS(r.amount-ABS(t.amount))>0.00001 LIMIT 1",
          "Transfer amount does not match its transactions")
    check({"transactions": ["id", "transfer_id"], "transfers": ["id", "outflow_transaction_id", "inflow_transaction_id"]},
          "SELECT 1 FROM transactions t LEFT JOIN transfers r ON r.id=t.transfer_id WHERE t.transfer_id IS NOT NULL AND (r.id IS NULL OR (t.id!=r.outflow_transaction_id AND t.id!=r.inflow_transaction_id)) LIMIT 1",
          "Invalid transaction transfer reference")
    check({"refund_allocations": ["refund_transaction_id", "original_transaction_id", "allocated_amount"], "transactions": ["id", "account_id", "currency"], "accounts": ["id", "family_id"]},
          "SELECT 1 FROM refund_allocations r LEFT JOIN transactions f ON f.id=r.refund_transaction_id LEFT JOIN transactions o ON o.id=r.original_transaction_id LEFT JOIN accounts a ON a.id=f.account_id LEFT JOIN accounts b ON b.id=o.account_id WHERE f.id IS NULL OR o.id IS NULL OR a.family_id IS NOT b.family_id OR r.allocated_amount<=0 LIMIT 1",
          "Invalid refund allocation")
    check({"transactions": ["id", "refund_of_transaction_id", "account_id", "currency"], "accounts": ["id", "family_id"]},
          "SELECT 1 FROM transactions f JOIN transactions o ON o.id=f.refund_of_transaction_id JOIN accounts a ON a.id=f.account_id JOIN accounts b ON b.id=o.account_id WHERE a.family_id IS NOT b.family_id OR f.id=o.id LIMIT 1",
          "Invalid direct refund relationship")
    check({"account_shares": ["account_id", "user_id"], "accounts": ["id", "family_id"], "users": ["id", "family_id"]},
          "SELECT 1 FROM account_shares s LEFT JOIN accounts a ON a.id=s.account_id LEFT JOIN users u ON u.id=s.user_id WHERE a.id IS NULL OR u.id IS NULL OR a.family_id IS NOT u.family_id LIMIT 1",
          "Share crosses a family boundary")
    check({"personal_debts": ["owner_id", "family_id"], "users": ["id", "family_id"]},
          "SELECT 1 FROM personal_debts d LEFT JOIN users u ON u.id=d.owner_id WHERE d.owner_id IS NOT NULL AND (u.id IS NULL OR u.family_id IS NOT d.family_id) LIMIT 1",
          "Debt owner belongs to another family")
    check({"transaction_splits": ["transaction_id", "category_id"], "transactions": ["id", "account_id"], "accounts": ["id", "family_id"], "categories": ["id", "family_id"]},
          "SELECT 1 FROM transaction_splits s JOIN transactions t ON t.id=s.transaction_id JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=s.category_id WHERE s.category_id IS NOT NULL AND (c.id IS NULL OR c.family_id IS NOT a.family_id) LIMIT 1",
          "Split category belongs to another family")
    check({"transaction_splits": ["transaction_id", "amount"], "transactions": ["id", "amount"]},
          "SELECT 1 FROM transaction_splits s JOIN transactions t ON t.id=s.transaction_id GROUP BY t.id,t.amount HAVING SUM(s.amount)>ABS(t.amount)+0.00001 OR MIN(s.amount)<0 LIMIT 1",
          "Invalid split amounts")
    for table, parent in (("accounts", "parent_account_id"), ("categories", "parent_id")):
        if {"id", parent} <= columns.get(table, set()):
            edges = dict(connection.execute(f'SELECT id,"{parent}" FROM "{table}"'))
            done = set()
            for start in edges:
                path = set()
                node = start
                while node in edges and node not in done:
                    if node in path:
                        problems.append(f"Cyclic relation: {table}")
                        break
                    path.add(node)
                    node = edges[node]
                done.update(path)
    if "original_amount" in columns.get("transactions", set()) and "refund_original_amount" in columns.get("refund_allocations", set()):
        for end, quantity in (("refund_transaction_id", "COALESCE(r.refund_original_amount,r.allocated_amount)"),
                              ("original_transaction_id", "r.allocated_amount")):
            check({"refund_allocations": [end, "allocated_amount"], "transactions": ["id", "amount", "original_amount"]},
                  f"SELECT 1 FROM refund_allocations r JOIN transactions t ON t.id=r.{end} GROUP BY t.id,t.amount,t.original_amount HAVING SUM({quantity})>ABS(COALESCE(t.original_amount,t.amount))+0.00001 LIMIT 1",
                  "Refund allocations exceed native transaction amount")
    else:
        for end in ("refund_transaction_id", "original_transaction_id"):
            check({"refund_allocations": [end, "allocated_amount"], "transactions": ["id", "amount"]},
                  f"SELECT 1 FROM refund_allocations r JOIN transactions t ON t.id=r.{end} GROUP BY t.id,t.amount HAVING SUM(r.allocated_amount)>ABS(t.amount)+0.00001 LIMIT 1",
                  "Refund allocations exceed transaction amount")
    check({"refund_allocations": ["refund_transaction_id", "original_transaction_id", "original_currency", "refund_original_amount", "original_book_amount", "refund_book_amount"], "transactions": ["id", "original_currency", "transaction_type"]},
          "SELECT 1 FROM refund_allocations r JOIN transactions f ON f.id=r.refund_transaction_id JOIN transactions o ON o.id=r.original_transaction_id WHERE f.transaction_type!='refund' OR o.transaction_type!='expense' OR (r.original_currency IS NOT NULL AND (r.original_currency IS NOT o.original_currency OR r.refund_original_amount<=0 OR r.original_book_amount<0 OR r.refund_book_amount<0 OR r.refund_original_amount IS NULL OR r.original_book_amount IS NULL OR r.refund_book_amount IS NULL)) LIMIT 1",
          "Invalid native refund metadata")
    check({"pending_fx_transactions": ["account_id", "family_id"], "accounts": ["id", "family_id"]},
          "SELECT 1 FROM pending_fx_transactions p JOIN accounts a ON a.id=p.account_id WHERE p.family_id IS NOT a.family_id LIMIT 1",
          "Pending transaction belongs to another family")
    return problems
