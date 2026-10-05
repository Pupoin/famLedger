"""Cache new Microsoft mail in SQLite and deliver exclusively from that cache."""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

from backend.auth.graph_auth import acquire_graph_token, cached_account_id
from backend.config import load_config
from backend.ingest.graph_client import GraphMailClient
from backend.ingest.famledger_sync import DeliveryBlocked, FamLedgerClient, sync_emails_and_parse_to_famledger
from backend.ingest.mail_store import MailStore

logger = logging.getLogger(__name__)
SCAN_VERSION = "uncapped-pages-v1"


class PendingDeliveryError(RuntimeError):
    """Known queued failures have already been logged with their individual reasons."""


def source_key(cfg, account_id):
    return hashlib.sha256(json.dumps([cfg.tenant_id, cfg.client_id, cfg.user_id, account_id]).encode()).hexdigest()


def deliver_cached(store, source, target, client, skip=(), window=None):
    processed = created = failed = 0
    attempted = set(skip)
    for row in store.pending(source, target):
        if row["graph_id"] in attempted:
            continue
        attempted.add(row["graph_id"])
        try:
            filters = {"since": datetime.fromisoformat(window["start"]),
                       "until": datetime.fromisoformat(window["end"])} if window else {}
            count, new = sync_emails_and_parse_to_famledger(client, {row["mail_kind"]: [json.loads(row["message_json"])]}, **filters)
            store.mark_delivery(source, row["graph_id"], target)
            processed += count
            created += new
        except Exception as error:
            store.mark_delivery(source, row["graph_id"], target, str(error)[:300])
            failed += 1
            logger.warning("Cached email delivery failed (%s): %s; it remains queued for retry",
                           type(error).__name__, str(error)[:300])
            if isinstance(error, DeliveryBlocked):
                # A target outage must not consume the entire task timeout before mail can be cached.
                return processed, created, failed, attempted, True
    return processed, created, failed, attempted, False


def cache_new_mail(store, source, cfg, graph):
    started = datetime.now(timezone.utc)
    listed_total = cached_total = 0
    for name, days, bank, subjects in [
        (cfg.credit_folder_name, cfg.lookback_days_credit, "ccsvc@message.cmbchina.com", ["每日信用管家", "近期消费明细"]),
        (cfg.debit_folder_name, cfg.lookback_days_debit, "95555@message.cmbchina.com", ["账户变动通知"]),
    ]:
        folder = store.folder(source, name)
        if folder is None:
            store.set_folder(source, name, graph.get_folder_id_by_name(name))
            folder = store.folder(source, name)
        history_days = store.history_days(source, name)
        # Compare against the last successful configuration, rather than the
        # largest historical window, so 3000 -> 50 -> 3000 rescans each change.
        rescan_history = days != history_days or store.scan_version(source, name) != SCAN_VERSION
        cursor = None if rescan_history else folder["delta_link"]
        mode = "history" if not cursor else "incremental"
        logger.info("Mail scan started: folder=%s lookback_days=%s previous_lookback_days=%s mode=%s",
                    name, days, history_days, mode)
        messages, delta_link = graph.delta_messages(folder["graph_id"], cursor)
        listed_total += len(messages)
        cached = already_cached = outside_window = ignored = 0
        first_cutoff = started - timedelta(days=days) if not cursor else None
        for message in messages:
            if "@removed" in message:
                ignored += 1
                continue
            if store.contains(source, message["id"]):
                already_cached += 1
                continue
            if first_cutoff and message.get("receivedDateTime") and datetime.fromisoformat(message["receivedDateTime"].replace("Z", "+00:00")) < first_cutoff:
                outside_window += 1
                continue
            sender = (message.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
            subject = message.get("subject", "")
            if sender and (sender != bank or not any(word in subject for word in subjects)):
                ignored += 1
                continue
            message = graph.get_message(message["id"])
            sender = (message.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
            if sender != bank or not any(word in message.get("subject", "") for word in subjects):
                ignored += 1
                continue
            kind = "credit_daily" if "每日信用管家" in message["subject"] else "credit_recent" if "近期消费明细" in message["subject"] else "debit"
            store.save_message(source, name, kind, message)
            cached += 1
            if cached % 50 == 0:
                logger.info("Mail scan progress: folder=%s cached=%s listed=%s", name, cached, len(messages))
        cached_total += cached
        store.complete_scan(source, name, started, delta_link, days, scan_version=SCAN_VERSION)
        logger.info("Mail scan completed: folder=%s mode=%s listed=%s cached=%s already_cached=%s outside_window=%s ignored=%s",
                    name, mode, len(messages), cached, already_cached, outside_window, ignored)
    return listed_total, cached_total


def run(fetch_new=True):
    cfg = load_config()
    fetch_new = fetch_new and cfg.pull_enabled
    if not fetch_new and not cfg.post_enabled:
        logger.info("Mail pull and POST are disabled for this run")
        return 0, 0
    client = None
    post_error = None
    if cfg.post_enabled:
        try:
            client = FamLedgerClient(cfg.api_url, cfg.api_token)
        except ValueError as error:
            post_error = error
            logger.warning("Mail POST configuration is invalid: %s; mail pull remains enabled=%s", error, fetch_new)
    # Target-specific delivery metadata allows a deliberate target change to
    # replay cached mail, with no credentials stored in SQLite.
    target = hashlib.sha256(json.dumps([cfg.api_url, cfg.api_token]).encode()).hexdigest() if client else None
    processed = created = failed = 0
    fetched = cached = 0
    attempted = {}
    blocked = False
    account = cached_account_id(cfg.token_cache_path) if client else None
    with MailStore(cfg.database_path) as store:
        def deliver_source(source):
            nonlocal processed, created, failed, blocked
            batches = [(target, None)]
            if cfg.replay_days:
                window = store.prepare_ranged_replay(source, target, cfg.replay_id, cfg.replay_days)
                if window:
                    batches.append((window["target"], window))
            else:
                store.prepare_replay(source, target, cfg.replay_id)
            for delivery_target, window in batches:
                key = (source, delivery_target)
                count, new, errors, tried, blocked = deliver_cached(
                    store, source, delivery_target, client, skip=attempted.get(key, ()), window=window)
                attempted[key] = tried
                processed += count
                created += new
                failed += errors
                if blocked:
                    break

        source = source_key(cfg, account) if account else None
        if client and source:
            deliver_source(source)
        if fetch_new:
            token, account = acquire_graph_token(cfg.tenant_id, cfg.client_id, cfg.graph_scopes, cfg.token_cache_path)
            verified_source = source_key(cfg, account)
            fetched, cached = cache_new_mail(store, verified_source, cfg, GraphMailClient(token, cfg.user_id))
            if client and not blocked:
                deliver_source(verified_source)
        elif client and not source:
            raise RuntimeError("A single cached Microsoft account is required for cached-only delivery")
    logger.info("Mail sync completed: fetched=%s, cached=%s, processed=%s, created=%s, failed=%s",
                fetched, cached, processed, created, failed)
    if failed:
        raise PendingDeliveryError(f"{failed} cached emails remain pending; retry next cycle")
    if post_error:
        raise PendingDeliveryError("POST configuration is invalid; configure FAMLEDGER_API_URL and FAMLEDGER_API_TOKEN; cached mail remains available for retry") from post_error
    return processed, created
