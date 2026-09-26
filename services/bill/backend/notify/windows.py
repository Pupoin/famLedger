from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path

from backend.ingest.stats import FinanceStats

logger = logging.getLogger(__name__)


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _normalize_launch_uri(url_or_path: str) -> str:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://") or url_or_path.startswith("file://"):
        return url_or_path
    return Path(url_or_path).resolve().as_uri()


def _copy_text_to_clipboard(value: str) -> bool:
    if not _is_windows():
        return False
    escaped = value.replace("'", "''")
    command = f"Set-Clipboard -Value '{escaped}'"
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except Exception as exc:
        logger.debug("复制验证码到剪贴板失败: %s", exc)
        return False


def _debit_breakdown(stats: FinanceStats) -> tuple[float, float, float]:
    if stats.detail_df.empty:
        return 0.0, 0.0, 0.0

    debit_df = stats.detail_df.loc[stats.detail_df["account"].astype(str) == "6061"].copy()
    if debit_df.empty:
        return 0.0, 0.0, 0.0

    debit_df["cost_float"] = debit_df["cost"].apply(float)
    behaviour = debit_df["behaviour"].astype(str)

    debit_in = float(debit_df.loc[(behaviour.isin(["转入", "入账"])) & (debit_df["cost_float"] > 0), "cost_float"].sum())
    debit_refund = float(debit_df.loc[(behaviour == "退款") & (debit_df["cost_float"] > 0), "cost_float"].sum())
    debit_out = float((-debit_df.loc[debit_df["cost_float"] < 0, "cost_float"]).sum())
    return debit_in, debit_refund, debit_out


def send_windows_notification(stats: FinanceStats, icon_path: str, launch_target: str = "") -> None:
    if not _is_windows():
        logger.info("当前非 Windows 平台，跳过系统通知。")
        return

    title = "招行账单自动化统计"
    debit_in, debit_refund, debit_out = _debit_breakdown(stats)
    report_uri = _normalize_launch_uri(launch_target) if launch_target else ""
    credit_out_total = abs(float(stats.month_credit_outcome) + float(stats.month_credit_income))
    month_out_total = abs(float(stats.month_outcome))
    message = (
        f"借记卡 入/退/出: {debit_in:.2f}/{debit_refund:.2f}/{debit_out:.2f}\n"
        f"信用卡总支出: {credit_out_total:.2f}\n"
        f"本月合计 入/出: {stats.month_income:.2f}/{month_out_total:.2f}\n"
        f"当前余额: {stats.current_balance:.2f}\n"
        + ("点击通知可打开账单页面" if report_uri else "")
    )

    icon = str(Path(icon_path)) if icon_path else None
    try:
        from winotify import Notification, audio

        try:
            toast = Notification(
                app_id="BillingGraph",
                title=title,
                msg=message,
                icon=icon if icon and Path(icon).exists() else "",
                launch=report_uri if report_uri else None,
            )
        except TypeError:
            toast = Notification(
                app_id="BillingGraph",
                title=title,
                msg=message,
                icon=icon if icon and Path(icon).exists() else "",
            )
            if hasattr(toast, "add_actions") and report_uri:
                toast.add_actions(label="打开账单", launch=report_uri)

        toast.set_audio(audio.Default, loop=False)
        toast.show()
        logger.debug("winotify 通知已发送（可进入通知中心，点击可跳转）")
        return
    except Exception as exc:
        logger.debug("winotify 通知发送失败，尝试 win10toast: %s", exc)

    try:
        from win10toast import ToastNotifier

        toaster = ToastNotifier()
        toaster.show_toast(
            title,
            message,
            icon_path=icon if icon and Path(icon).exists() else None,
            duration=5,
            threaded=True,
        )
        logger.debug("win10toast 通知已异步发送（该后端不支持点击跳转）")
        return
    except Exception as exc:
        logger.debug("win10toast 通知发送失败，尝试 plyer: %s", exc)

    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            app_icon=icon if icon and Path(icon).exists() else None,
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Windows 通知发送失败: %s", exc)


def send_auth_notification(
    user_code: str,
    verify_url: str,
    *,
    verify_url_complete: str = "",
    client_id: str = "",
) -> None:
    if not _is_windows():
        logger.warning("非 Windows 平台不发送系统通知，请手动打开认证页面: %s，验证码: %s", verify_url, user_code)
        return

    title = "Graph 认证需要操作"
    target_url = verify_url_complete or verify_url
    target = _normalize_launch_uri(target_url)

    copied = _copy_text_to_clipboard(user_code)
    suffix = f"\n应用ID: {client_id}" if client_id else ""
    quick_hint = "\n通知支持一键打开并自动带码。" if verify_url_complete else ""
    copy_hint = "\n验证码已复制到剪贴板。" if copied else "\n验证码复制失败，请手动复制。"
    message = (
        f"设备验证码: {user_code}\n"
        "点击通知可打开认证页面。"
        f"{copy_hint}"
        f"{quick_hint}"
        f"{suffix}"
    )

    try:
        from winotify import Notification, audio

        try:
            toast = Notification(
                app_id="BillingGraph",
                title=title,
                msg=message,
                launch=target,
            )
        except TypeError:
            toast = Notification(
                app_id="BillingGraph",
                title=title,
                msg=message,
            )
            if hasattr(toast, "add_actions"):
                if verify_url_complete:
                    toast.add_actions(label="一键认证", launch=_normalize_launch_uri(verify_url_complete))
                toast.add_actions(label="打开认证页", launch=_normalize_launch_uri(verify_url))

        toast.set_audio(audio.Default, loop=False)
        toast.show()
        logger.info("已发送认证通知，等待用户完成认证。user_code=%s", user_code)
        return
    except Exception as exc:
        logger.debug("认证通知发送失败，降级输出日志: %s", exc)

    logger.warning("请打开认证页面并输入验证码: url=%s user_code=%s", verify_url, user_code)
