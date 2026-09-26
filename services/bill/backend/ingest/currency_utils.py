from __future__ import annotations

import logging
import requests
from datetime import datetime
from decimal import Decimal
from functools import lru_cache

logger = logging.getLogger(__name__)

# 缓存汇率，避免重复请求
@lru_cache(maxsize=200)
def get_exchange_rates(date_str: str, from_curr: str) -> dict[str, float] | None:
    """
    获取指定日期的汇率。
    date_str: YYYY-MM-DD
    """
    url = f"https://api.frankfurter.app/{date_str}?from={from_curr}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("rates")
    except Exception as e:
        logger.error(f"获取汇率失败: {url}, error: {e}")
        return None

def convert_to_cny(amount: Decimal, currency: str, date: datetime) -> Decimal:
    """
    将外币转换为人民币。
    遵循严格路径：任何非人民币交易 -> USD -> CNY。
    """
    curr = currency.upper().strip()
    if curr in ("CNY", "￥", "¥", "RMB"):
        return amount

    date_str = date.strftime("%Y-%m-%d")

    # 1. 如果本身就是 USD，直接转 CNY
    if curr == "USD":
        usd_rates = get_exchange_rates(date_str, "USD")
        if usd_rates and "CNY" in usd_rates:
            rate = Decimal(str(usd_rates["CNY"]))
            logger.debug(f"直接转换 USD -> CNY: rate={rate}")
            return amount * rate
        else:
            # 兜底：如果 API 失败，使用固定汇率
            logger.warning(f"无法获取 USD/CNY 实时汇率，使用兜底汇率 7.2")
            return amount * Decimal("7.2")

    # 2. 如果是其他外币（如 SGD），严格执行 Other -> USD -> CNY
    
    # 第一步：Other -> USD
    other_rates = get_exchange_rates(date_str, curr)
    if not other_rates or "USD" not in other_rates:
        # 兜底逻辑
        fallback_to_usd = {"SGD": Decimal("0.74"), "HKD": Decimal("0.128")}
        rate_to_usd = fallback_to_usd.get(curr, Decimal("1")) # 未知货币默认 1:1 转 USD (不推荐)
        logger.warning(f"无法获取 {curr}/USD 实时汇率，使用兜底: {rate_to_usd}")
        usd_amount = amount * rate_to_usd
    else:
        rate_to_usd = Decimal(str(other_rates["USD"]))
        usd_amount = amount * rate_to_usd
        logger.debug(f"转换第一步 {curr} -> USD: rate={rate_to_usd}, result_usd={usd_amount}")

    # 第二步：USD -> CNY (使用同一天的汇率)
    usd_rates = get_exchange_rates(date_str, "USD")
    if not usd_rates or "CNY" not in usd_rates:
        rate_usd_to_cny = Decimal("7.2")
        logger.warning(f"无法获取 USD/CNY 实时汇率，使用兜底: {rate_usd_to_cny}")
    else:
        rate_usd_to_cny = Decimal(str(usd_rates["CNY"]))
        logger.debug(f"转换第二步 USD -> CNY: rate={rate_usd_to_cny}")

    final_cny = usd_amount * rate_usd_to_cny
    logger.info(f"外币折算完成: {amount} {curr} -> {usd_amount:.4f} USD -> {final_cny:.2f} CNY (日期: {date_str})")
    return final_cny
