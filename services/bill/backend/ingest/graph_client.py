from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)


class GraphMailClient:
    RETRYABLE_STATUS_CODES = { 429, 500, 502, 503, 504 }

    def __init__(
        self,
        access_token: str,
        user_id: str = "me",
        *,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ) -> None:
        self.user_id = user_id
        self.base_url = f"https://graph.microsoft.com/v1.0/users/{user_id}" if user_id != "me" else "https://graph.microsoft.com/v1.0/me"
        self.timeout = (
            connect_timeout if connect_timeout is not None else float(os.getenv("GRAPH_CONNECT_TIMEOUT_SECONDS", "10")),
            read_timeout if read_timeout is not None else float(os.getenv("GRAPH_READ_TIMEOUT_SECONDS", "60")),
        )
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("GRAPH_MAX_RETRIES", "3"))
        self.retry_backoff_seconds = (
            retry_backoff_seconds
            if retry_backoff_seconds is not None
            else float(os.getenv("GRAPH_RETRY_BACKOFF_SECONDS", "1"))
        )
        if self.max_retries < 0:
            raise ValueError("GRAPH_MAX_RETRIES must be zero or greater")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        logger.debug("Graph GET: url=%s params=%s", url, params)
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                if attempt >= self.max_retries:
                    raise

                delay = self.retry_backoff_seconds * (2 ** attempt)
                logger.warning(
                    "Graph 请求超时或连接失败，将重试: attempt=%s/%s delay=%.1fs error=%s",
                    attempt + 1,
                    self.max_retries,
                    delay,
                    exc,
                )
                time.sleep(delay)
                continue

            if response.status_code in self.RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                delay = self._retry_delay(response, attempt)
                logger.warning(
                    "Graph 返回可重试状态，将重试: status=%s attempt=%s/%s delay=%.1fs",
                    response.status_code,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                response.close()
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        raise RuntimeError("Graph request retry loop exited unexpectedly")

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                # Microsoft Graph normally sends Retry-After as seconds for throttling.
                return min(max(float(retry_after), 0), 60)
            except ValueError:
                logger.debug("忽略无法识别的 Graph Retry-After: %r", retry_after)

        return self.retry_backoff_seconds * (2 ** attempt)

    def _list_folders(self, url: str) -> list[dict[str, Any]]:
        folders: list[dict[str, Any]] = []
        next_link: str | None = url
        while next_link:
            data = self._get(next_link)
            folders.extend(data.get("value", []))
            next_link = data.get("@odata.nextLink")
        logger.debug("Graph 文件夹列表获取完成: count=%s", len(folders))
        return folders

    def get_folder_id_by_name(self, folder_name: str) -> str:
        # 优先从 Inbox 的子目录查找，兼容你原脚本 `inbox.Folders("credits")` 的结构。
        inbox_children_url = f"{self.base_url}/mailFolders/inbox/childFolders?$top=200"
        top_folders_url = f"{self.base_url}/mailFolders?$top=200"

        folders = self._list_folders(inbox_children_url) + self._list_folders(top_folders_url)
        logger.debug("匹配文件夹：target=%s available=%s", folder_name, [f.get("displayName") for f in folders])
        for folder in folders:
            if folder.get("displayName", "").lower() == folder_name.lower():
                logger.info("已命中文件夹: %s", folder_name)
                return folder["id"]
        raise ValueError(f"未找到邮件文件夹: {folder_name}")

    def list_messages(
        self,
        folder_id: str,
        sender: str,
        subject_keywords: list[str],
        lookback_days: int,
        since_at: datetime | None = None,
        include_all: bool = False,
    ) -> list[dict[str, Any]]:
        since = (since_at or datetime.now(timezone.utc) - timedelta(days=lookback_days)).astimezone(timezone.utc).isoformat()
        sender_lower = sender.lower()
        messages: list[dict[str, Any]] = []

        url = f"{self.base_url}/mailFolders/{folder_id}/messages"
        params: dict[str, Any] = {
            "$top": 50,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,body,bodyPreview,receivedDateTime",
            "$filter": f"receivedDateTime ge {since}",
        }

        while url:
            data = self._get(url, params=params)
            page_items = data.get("value", [])
            logger.debug("消息分页读取: folder_id=%s page_size=%s", folder_id, len(page_items))
            for item in data.get("value", []):
                from_addr = (item.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
                subject = item.get("subject", "")
                if not include_all:
                    if from_addr != sender_lower:
                        continue
                    if not any(keyword in subject for keyword in subject_keywords):
                        continue
                messages.append(item)
                logger.debug(
                    "命中邮件: subject=%s from=%s received=%s",
                    subject,
                    from_addr,
                    item.get("receivedDateTime"),
                )

            url = data.get("@odata.nextLink")
            params = None
        logger.debug("邮件筛选完成: folder_id=%s sender=%s count=%s", folder_id, sender, len(messages))
        return messages
