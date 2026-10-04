import datetime
from decimal import Decimal
import uuid
import pytest
from sqlmodel import Session, select

from models import Account, Category, Family, Transaction, TransactionSplit, User
from services.stats_engine import compute_netted_category_distribution


def test_split_stats_engine_distribution():
    """测试 stats_engine 在存在拆分交易时的分类归集精确性与总额守恒。"""
    cat_dining = Category(id=uuid.uuid4(), name="餐饮美食", icon="🍴")
    cat_groceries = Category(id=uuid.uuid4(), name="超市便利", icon="🛒")
    category_map = {cat_dining.id: cat_dining, cat_groceries.id: cat_groceries}

    # 1. 构造一笔未拆分交易 ¥500 (归属于餐饮美食)
    t1 = Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        amount=Decimal("500.00"),
        transaction_type="expense",
        category_id=cat_dining.id,
        narration="聚餐",
        is_split=False,
    )

    # 2. 构造一笔拆分交易 ¥300 (原为未分类/其他)，拆分为：
    #    子项 1: ¥200 -> 超市便利
    #    子项 2: ¥100 -> 餐饮美食
    t2 = Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        amount=Decimal("300.00"),
        transaction_type="expense",
        category_id=None,
        narration="沃尔玛与外卖合单",
        is_split=True,
    )

    s1 = TransactionSplit(
        id=uuid.uuid4(),
        transaction_id=t2.id,
        category_id=cat_groceries.id,
        amount=Decimal("200.00"),
        notes="买菜",
    )
    s2 = TransactionSplit(
        id=uuid.uuid4(),
        transaction_id=t2.id,
        category_id=cat_dining.id,
        amount=Decimal("100.00"),
        notes="奶茶",
    )

    splits_map = {t2.id: [s1, s2]}

    # 运行计算
    categories_data, total_net, total_gross, total_refund = compute_netted_category_distribution(
        [t1, t2], [], category_map, splits_map=splits_map
    )

    # 验证总支出
    assert total_gross == 800.00
    assert total_net == 800.00

    # 验证分类细分：
    # 餐饮美食: t1(500) + s2(100) = 600
    # 超市便利: s1(200) = 200
    cat_res = {c["name"]: c["amount"] for c in categories_data}
    assert cat_res["餐饮美食"] == 600.00
    assert cat_res["超市便利"] == 200.00

    # 资金绝对守恒
    assert sum(cat_res.values()) == 800.00


def test_split_refund_netting():
    """测试退款拆分时各子项精确冲抵对应分类并保证净额资金守恒。"""
    cat_dining = Category(id=uuid.uuid4(), name="餐饮美食", icon="🍴")
    cat_groceries = Category(id=uuid.uuid4(), name="超市便利", icon="🛒")
    category_map = {cat_dining.id: cat_dining, cat_groceries.id: cat_groceries}

    # 支出：餐饮美食 ¥500，超市便利 ¥300
    t1 = Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        amount=Decimal("500.00"),
        transaction_type="expense",
        category_id=cat_dining.id,
        narration="海底捞",
    )
    t2 = Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        amount=Decimal("300.00"),
        transaction_type="expense",
        category_id=cat_groceries.id,
        narration="山姆会员店",
    )

    # 退款 ¥200，拆分为：
    # 子项 1: ¥150 -> 冲抵餐饮美食
    # 子项 2: ¥50  -> 冲抵超市便利
    r1 = Transaction(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        amount=Decimal("200.00"),
        transaction_type="refund",
        category_id=None,
        narration="合并退款",
        is_split=True,
    )
    s1 = TransactionSplit(
        id=uuid.uuid4(),
        transaction_id=r1.id,
        category_id=cat_dining.id,
        amount=Decimal("150.00"),
        notes="餐饮退单",
    )
    s2 = TransactionSplit(
        id=uuid.uuid4(),
        transaction_id=r1.id,
        category_id=cat_groceries.id,
        amount=Decimal("50.00"),
        notes="商品缺货退款",
    )
    splits_map = {r1.id: [s1, s2]}

    categories_data, total_net, total_gross, total_refund = compute_netted_category_distribution(
        [t1, t2], [r1], category_map, splits_map=splits_map
    )

    # 验证总额
    assert total_gross == 800.00
    assert total_refund == 200.00
    assert total_net == 600.00

    # 验证分类被拆分退款精确冲抵：
    # 餐饮美食: 500 - 150 = 350
    # 超市便利: 300 - 50 = 250
    cat_res = {c["name"]: c["amount"] for c in categories_data}
    assert cat_res["餐饮美食"] == 350.00
    assert cat_res["超市便利"] == 250.00
    assert sum(cat_res.values()) == total_net == 600.00
