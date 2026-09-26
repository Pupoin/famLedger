from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import pyodbc
except ModuleNotFoundError:
    pyodbc = None

from backend.ingest.db import CMB_BILL_TABLE, ensure_bill_table, get_connection


def _access_conn_str(accdb_path: str) -> str:
    return f"Driver={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={accdb_path};"


def _resolve_accdb_path(accdb_path: str) -> Path:
    candidate = Path(accdb_path).expanduser().resolve()
    if candidate.exists() and candidate.is_file():
        return candidate

    parent = candidate.parent if candidate.parent.exists() else Path.cwd()
    siblings = sorted(parent.glob("*.accdb"))
    near = [item for item in siblings if candidate.stem.lower() in item.stem.lower() or item.stem.lower() in candidate.stem.lower()]

    if near:
        return near[0]

    available = ", ".join(str(item.name) for item in siblings) if siblings else "无"
    raise FileNotFoundError(f"未找到 Access 文件: {candidate}。当前目录可用 .accdb: {available}")


def _pick_access_source_tables(cursor: Any) -> list[str]:
    tables = [row.table_name for row in cursor.tables(tableType="TABLE")]
    if CMB_BILL_TABLE in tables:
        return [CMB_BILL_TABLE]

    year_tables = [table for table in tables if re.match(r"^expenditure_\d{4}$", table)]
    if year_tables:
        return sorted(year_tables)

    raise RuntimeError("Access 中未发现可迁移表（需要 CMB_bill 或 expenditure_YYYY）。")


def _get_source_rows(cursor: Any, table: str) -> list[tuple]:
    columns = {str(col.column_name).lower() for col in cursor.columns(table=table)}
    business_col = "bussiness" if "bussiness" in columns else "business"
    remain_expr = "remain" if "remain" in columns else "NULL AS remain"
    source_expr = "source" if "source" in columns else "'' AS source"
    query = (
        f"SELECT costTime, cost, account, behaviour, {business_col}, {remain_expr}, {source_expr} "
        f"FROM [{table}]"
    )
    return cursor.execute(query).fetchall()


def migrate_access_to_postgres(accdb_path: str, pg_dsn: str) -> None:
    if pyodbc is None:
        raise RuntimeError("当前环境未安装 pyodbc，无法执行 Access 迁移。")

    resolved_path = _resolve_accdb_path(accdb_path)
    print(f"使用 Access 文件: {resolved_path}")
    access_conn = pyodbc.connect(_access_conn_str(str(resolved_path)))
    pg_conn = get_connection(pg_dsn)

    try:
        cursor = access_conn.cursor()
        source_tables = _pick_access_source_tables(cursor)

        total_rows = 0
        inserted_rows = 0

        ensure_bill_table(pg_conn)
        pg_conn.commit()

        for table in source_tables:
            rows = _get_source_rows(cursor, table)

            with pg_conn.cursor() as pg_cur:
                for row in rows:
                    total_rows += 1
                    cost_time = row[0]
                    if isinstance(cost_time, str):
                        cost_time = datetime.fromisoformat(cost_time)
                    pg_cur.execute(
                        f'''
                        INSERT INTO "{CMB_BILL_TABLE}" (costTime, cost, account, behaviour, business, remain, source, original_cost, original_currency)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (costTime, original_cost, original_currency) DO NOTHING;
                        ''',
                        (
                            cost_time,
                            float(row[1] or 0),
                            row[2] or "",
                            row[3] or "",
                            row[4] or "",
                            str(row[5]) if row[5] is not None else "",
                            row[6] or "",
                            float(row[1] or 0), # 迁移数据默认 original = converted
                            "CNY",              # 迁移数据默认 CNY
                        ),
                    )
                    inserted_rows += max(pg_cur.rowcount, 0)
            pg_conn.commit()
            print(f"{table} -> {CMB_BILL_TABLE} 迁移完成")

        print(f"迁移结束：Access 读取 {total_rows} 条，PostgreSQL 新增 {inserted_rows} 条。")
    finally:
        access_conn.close()
        pg_conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 Access 账单库到 PostgreSQL")
    parser.add_argument("--accdb", required=True, help="Access .accdb 文件绝对路径")
    parser.add_argument("--pg-dsn", required=True, help="PostgreSQL DSN")
    args = parser.parse_args()

    migrate_access_to_postgres(args.accdb, args.pg_dsn)


if __name__ == "__main__":
    main()
