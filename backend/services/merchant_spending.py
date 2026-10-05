"""One merchant ranking for the spending chart and its Other drilldown."""
from decimal import Decimal

MERCHANT_TILE_LIMIT = 7


def ranked_merchants(expenses):
    totals, counts = {}, {}
    for activity in expenses:
        name = activity.narration or '其他'
        totals[name] = totals.get(name, Decimal(0)) + activity.amount
        counts[name] = counts.get(name, 0) + 1
    # Break equal-amount ties consistently across separate HTTP requests.
    return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0])), counts
