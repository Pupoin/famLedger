"""One interpretation of the direction of a stored transaction."""
from models import Transfer


def transaction_direction(txn, session=None, account=None):
    if txn.transaction_type == "expense":
        return "outflow"
    if txn.transaction_type in ("income", "refund"):
        return "inflow"
    if txn.transaction_type != "transfer":
        return None
    if txn.transfer_id and session is not None:
        pair = session.get(Transfer, txn.transfer_id)
        if pair:
            if pair.outflow_transaction_id == txn.id:
                return "outflow"
            if pair.inflow_transaction_id == txn.id:
                return "inflow"
    direction = (txn.extra or {}).get("direction")
    if direction in ("in", "inflow"):
        return "inflow"
    if direction in ("out", "outflow"):
        return "outflow"
    text = f"{txn.narration or ''} {txn.notes or ''}".lower()
    incoming = ["转入", "收到", "存入", "收款", "入账", "汇入", "转自", "inflow", "transfer from"]
    if getattr(account, "classification", None) == "liability":
        incoming += ["还款", "扣缴", "偿还", "还清", "冲减", "结清"]
    if getattr(account, "account_type", None) == "iou":
        incoming += ["借据", "借出", "出具", "放款"]
    return "inflow" if any(word in text for word in incoming) else "outflow"
