"""Historical FX quotes persisted in the database; fixed account bookings stay unchanged."""
from decimal import Decimal, InvalidOperation
from datetime import date, datetime, timezone
import requests
from fastapi import HTTPException
from sqlmodel import select
from models import Family, UserPreference, VALID_CURRENCIES, CURRENCY_SYMBOLS, ExchangeRateSnapshot


def _valid_rates(raw):
    if not isinstance(raw, dict):
        raise ValueError("无效汇率响应")
    rates = {code: Decimal(str(value)) for code, value in raw.items()}
    if any(not value.is_finite() or value <= 0 for value in rates.values()):
        raise ValueError("无效汇率")
    rates["EUR"] = Decimal(1)
    return rates


def exchange_rates(session, quote_day):
    """Check that day's database entry before fetching the requested date."""
    if not isinstance(quote_day, date):
        quote_day = date.fromisoformat(quote_day)
    if quote_day > date.today():
        raise HTTPException(422, detail="未来日期尚无汇率")
    key = (quote_day, "EUR")
    saved = session.get(ExchangeRateSnapshot, key)
    if saved:
        try:
            rates = _valid_rates(saved.rates)
            if saved.effective_date > quote_day or (quote_day - saved.effective_date).days > 7:
                raise ValueError("无效汇率日期")
            return rates, saved.effective_date
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise HTTPException(502, detail="数据库中的汇率无效，请检查汇率数据") from exc
    from services.transaction_lock import lock_mutation
    lock_mutation(session)
    saved = session.get(ExchangeRateSnapshot, key)
    if saved:
        return _valid_rates(saved.rates), saved.effective_date
    try:
        response = requests.get(
            f"https://api.frankfurter.app/{quote_day.isoformat()}", params={"from": "EUR"}, timeout=8
        )
        response.raise_for_status()
        data = response.json()
        if data.get("base") != "EUR":
            raise ValueError("汇率基准币种不匹配")
        rates = _valid_rates(data["rates"])
        effective_date = date.fromisoformat(data["date"])
        if effective_date > quote_day or (quote_day - effective_date).days > 7:
            raise ValueError("汇率日期无效")
    except (requests.RequestException, KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise HTTPException(502, detail=f"无法取得 {quote_day.isoformat()} 的有效汇率，请稍后重试") from exc
    # Racing requests may miss the same key. Keep the first validated quote,
    # without committing or rolling back unrelated mutations in this session.
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(ExchangeRateSnapshot).values(
        requested_date=quote_day, base_currency="EUR", effective_date=effective_date,
        rates={code: str(value) for code, value in rates.items()}, provider="frankfurter",
        fetched_at=datetime.now(timezone.utc)
    ).on_conflict_do_nothing(index_elements=["requested_date", "base_currency"])
    session.execute(statement)
    session.info["fx_cache_written"] = True
    saved = session.get(ExchangeRateSnapshot, key)
    return _valid_rates(saved.rates), saved.effective_date


def persist_fx_cache(session):
    """Commit quotes at the end of successful read handlers; writes commit normally."""
    if session.info.pop("fx_cache_written", False):
        session.commit()


class ReportCurrency:
    def __init__(self, session, user=None, currency=None, cache_independently=False):
        family = session.get(Family, user.family_id) if user and user.family_id else None
        pref = session.exec(select(UserPreference).where(UserPreference.username == user.username)).first() if user else None
        self.currency = currency or (pref.currency if pref else (family.currency if family else "CNY"))
        if self.currency not in VALID_CURRENCIES:
            raise HTTPException(422, detail="展示币种不受支持")
        self.symbol = CURRENCY_SYMBOLS[self.currency]
        self.session = session
        self.cache_independently = cache_independently
        self._quotes = {}
        self.account_ids = set()

    def amount(self, value, source, on_date=None):
        value = Decimal(str(value or 0))
        if not value.is_finite():
            raise HTTPException(422, detail="金额必须为有限数字")
        if source == self.currency or not value:
            return value
        on_date = on_date or date.today()
        if isinstance(on_date, str):
            on_date = date.fromisoformat(on_date)
        if on_date not in self._quotes:
            if self.cache_independently:
                from sqlmodel import Session
                # Report reads retain no write lock across a whole historical
                # range; each daily quote commits in its own short transaction.
                with Session(self.session.get_bind()) as cache_session:
                    self._quotes[on_date] = exchange_rates(cache_session, on_date)
                    persist_fx_cache(cache_session)
            else:
                self._quotes[on_date] = exchange_rates(self.session, on_date)
        rates, _ = self._quotes[on_date]
        if source not in rates or self.currency not in rates:
            raise HTTPException(502, detail=f"缺少 {on_date.isoformat()} 的 {source}/{self.currency} 汇率")
        return value * rates[self.currency] / rates[source]

    def uses_master(self, txn):
        if txn.master_account_id and txn.master_account_id in self.account_ids:
            from models import Account
            account = self.session.get(Account, txn.account_id)
            return bool(account and account.parent_account_id == txn.master_account_id and txn.master_settlement_amount is not None)
        return False

    def ledger_amount(self, txn, value=None):
        value = txn.amount if value is None else Decimal(str(value))
        if self.uses_master(txn):
            from services.booking_money import money
            value = money(txn.master_settlement_amount * value / txn.amount) if txn.amount else Decimal(0)
            return self.amount(value, txn.master_settlement_currency, txn.transacted_at)
        if self.account_ids:
            from models import Account
            account = self.session.get(Account, txn.account_id)
            if account and account.parent_account_id in self.account_ids:
                parent = self.session.get(Account, account.parent_account_id)
                if parent and parent.currency != account.currency:
                    raise HTTPException(409, "报表中的外币副卡缺少固定主卡结算，请先核对")
        return self.amount(value, txn.currency, txn.transacted_at)

    def transactions(self, transactions):
        return [t.model_copy(update={"amount": self.ledger_amount(t), "currency": self.currency}) for t in transactions]

    def splits(self, splits, original_transactions):
        parents = {t.id: t for t in original_transactions}
        return [s.model_copy(update={"amount": self.ledger_amount(parents[s.transaction_id], s.amount)}) for s in splits]

    def metadata(self):
        return {"currency": self.currency, "currency_symbol": self.symbol,
                "exchange_rate_basis": "fixed_account_booking; fixed_master_settlement; report_at_transaction_date; valuation_at_today",
                "exchange_rate_dates": {day.isoformat(): effective.isoformat()
                                        for day, (_, effective) in sorted(self._quotes.items())}}
