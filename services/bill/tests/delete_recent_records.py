import sys
from pathlib import Path

# Add project root to sys.path to allow imports from backend
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from datetime import datetime, timedelta
import logging
from backend.ingest.config import load_config
from backend.ingest.db import get_connection, CMB_BILL_TABLE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def delete_recent_records(days: int = 5):
    cfg = load_config()
    cutoff = datetime.now() - timedelta(days=days)
    
    logger.info(f"Connecting to database to delete records newer than {cutoff} ({days} days)...")
    
    try:
        with get_connection(cfg.pg_dsn) as conn:
            with conn.cursor() as cur:
                sql = f'DELETE FROM "{CMB_BILL_TABLE}" WHERE costTime >= %s'
                cur.execute(sql, (cutoff,))
                count = cur.rowcount
                conn.commit()
                logger.info(f"Successfully deleted {count} records.")
    except Exception as e:
        logger.error(f"Failed to delete records: {e}")

if __name__ == "__main__":
    delete_recent_records(1000000)
