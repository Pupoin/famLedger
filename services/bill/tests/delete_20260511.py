import sys
from pathlib import Path

# Add project root to sys.path to allow imports from backend
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.ingest.config import load_config
from backend.ingest.db import get_connection

def main():
    target_date = "2026-06-01"  # 要删除的日期，格式为 YYYY-MM-DD
    cfg = load_config()
    
    # 从宿主机访问时，需要将 localhost:5432 改为 localhost:15432
    dsn = cfg.pg_dsn.replace(":5432", ":15432")
    
    print(f"Connecting to database via {dsn}...")
    
    try:
        conn = get_connection(dsn)
        with conn:
            with conn.cursor() as cur:
                # 删除指定日期的所有流水记录
                # 注意：PostgreSQL 默认列名为小写 costtime
                sql = 'DELETE FROM "CMB_bill" WHERE "costtime"::date > %s'
                print(f"Executing cleanup for {target_date}...")
                cur.execute(sql, (target_date,))
                count = cur.rowcount
                print(f"✅ Successfully deleted {count} records for {target_date}.")
        conn.close()
    except Exception as e:
        print(f"❌ Error occurred: {e}")
        print("\n提示：如果在宿主机运行失败，请尝试在容器内运行：")
        print(f"sudo docker exec bill-backend python3 -c \"import psycopg; conn = psycopg.connect('{cfg.pg_dsn.replace('localhost', 'postgres')}'); cur = conn.cursor(); cur.execute('DELETE FROM \\\"CMB_bill\\\" WHERE \\\"costtime\\\"::date = \\'2026-05-11\\''); print(f'Deleted {{cur.rowcount}} records'); conn.commit(); conn.close()\"")

if __name__ == "__main__":
    main()
