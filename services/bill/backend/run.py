from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import signal
import time
from datetime import datetime

from dotenv import load_dotenv

from backend.auth.graph_auth import validate_cached_graph_auth
from backend.auth.state import set_auth_failed, set_auth_ok
from backend.ingest.config import load_config
from backend.ingest.pipeline import run

load_dotenv()

CHECK_INTERVAL_SECONDS = 20
AUTH_FAIL_WAIT_SECONDS = 60
BILL_SYNC_INTERVAL_SECONDS = int(os.getenv("BILL_SYNC_INTERVAL_SECONDS", "600"))
if BILL_SYNC_INTERVAL_SECONDS < 60:
    raise ValueError("BILL_SYNC_INTERVAL_SECONDS must be at least 60")
TASK_TIMEOUT_SECONDS = int(os.getenv("BILL_TASK_TIMEOUT_SECONDS", "1000"))

logger = logging.getLogger(__name__)


def _check_auth_once() -> bool:
    cfg = load_config()
    is_ok = validate_cached_graph_auth(
        tenant_id=cfg.tenant_id,
        client_id=cfg.client_id,
        scopes=cfg.graph_scopes,
        token_cache_path=cfg.token_cache_path,
    )
    if is_ok:
        set_auth_ok()
        logger.debug("Graph auth is valid")
    else:
        set_auth_failed(
            "检测到 Graph 认证失效，可点击页面中的登录按钮重新认证（仅提醒）。",
            client_id=cfg.client_id,
        )
        logger.warning("Graph auth invalid, waiting for user re-authentication")
    return is_ok


def _worker_task() -> None:
    """子进程执行的任务：认证校验与账单拉取。"""
    try:
        # 这里不再使用 AUTH_FAIL_WAIT_SECONDS 逻辑，因为 worker 应该是快速失败或成功的
        if not _check_auth_once():
            logger.info("[worker] Graph 认证失效，跳过本次执行")
            return
        run()
    except Exception as exc:
        logger.exception("[worker] 任务执行过程中发生异常: %s", exc)


def _run_once() -> None:
    """使用多进程看门狗运行一次任务。"""
    # 考虑到 _check_auth_once 本身也可能因为网络挂起，整个过程都放入子进程
    p = multiprocessing.Process(target=_worker_task, name="BillWorker")
    p.start()
    logger.debug("[main] 子进程已启动 (PID: %s)", p.pid)

    p.join(timeout=TASK_TIMEOUT_SECONDS)

    if p.is_alive():
        logger.error("[main] 任务执行超时（超过 %s 秒），强制终止子进程 (PID: %s)", TASK_TIMEOUT_SECONDS, p.pid)
        p.terminate()
        time.sleep(2)
        if p.is_alive():
            os.kill(p.pid, signal.SIGKILL)
            logger.error("[main] 已发送 SIGKILL 终止子进程 %s", p.pid)
    else:
        if p.exitcode != 0:
            logger.warning("[main] 子进程执行结束，退出码非零: %s", p.exitcode)
        else:
            logger.debug("[main] 子进程正常结束")


def run_scheduler() -> None:
    last_run_at: datetime | None = None

    cfg = load_config()

    logger.info("[scheduler] first run now; then run every %s seconds", BILL_SYNC_INTERVAL_SECONDS)

    logger.info("[scheduler] startup trigger")
    _run_once()
    last_run_at = datetime.now()

    while True:
        now = datetime.now()
        sync_due = last_run_at is None or (now - last_run_at).total_seconds() >= BILL_SYNC_INTERVAL_SECONDS
        if sync_due:
            logger.info("[scheduler] trigger at %s", now.strftime("%Y-%m-%d %H:%M"))
            _run_once()
            last_run_at = datetime.now()
        time.sleep(CHECK_INTERVAL_SECONDS)


def main() -> None:
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Bill automation scheduler")
    parser.add_argument("--once", action="store_true", help="Run once immediately and exit")
    args = parser.parse_args()

    if args.once:
        _run_once()
        return

    run_scheduler()


if __name__ == "__main__":
    main()
