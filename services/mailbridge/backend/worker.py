import argparse
import logging
import multiprocessing
import time
from backend.config import load_config
from backend.ingest.pipeline import PendingDeliveryError, run

logger = logging.getLogger(__name__)


def _worker(fetch_new):
    try:
        run(fetch_new=fetch_new)
    except PendingDeliveryError as error:
        logger.error("Mail sync incomplete: %s", error)
        raise SystemExit(1) from None
    except Exception:
        logger.exception("Mail sync failed; cached mail remains available for retry")
        raise SystemExit(1) from None


def run_once(fetch_new=True):
    cfg = load_config()
    fetch_new = fetch_new and cfg.pull_enabled
    if not fetch_new and not cfg.post_enabled:
        logger.info("Mail pull and POST are disabled for this run")
        return 0
    logger.info("Mail task started: pull_enabled=%s post_enabled=%s", fetch_new, cfg.post_enabled)
    process = multiprocessing.Process(target=_worker, args=(fetch_new,), name="MailSync")
    process.start()
    process.join(cfg.task_timeout)
    if process.is_alive():
        process.terminate()
        process.join(3)
        if process.is_alive():
            process.kill()
            process.join()
        logger.error("Mail sync timed out; retry next cycle")
        return 1
    return 0 if process.exitcode == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Microsoft bank mail to famLedger")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cached-only", action="store_true", help="Retry local cached mail without Microsoft requests")
    args = parser.parse_args()
    cfg = load_config()
    while True:
        exit_code = run_once(fetch_new=not args.cached_only)
        if args.once or args.cached_only:
            raise SystemExit(exit_code)
        time.sleep(cfg.sync_interval)


if __name__ == "__main__":
    main()
