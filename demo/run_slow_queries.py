#!/usr/bin/env python3
"""
Run a suite of intentionally inefficient queries N times each
and print per-execution elapsed time.

Usage:
    export PGPASSWORD='your_password'
    python run_slow_queries.py
"""
import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Connection parameters
# ---------------------------------------------------------------------------
DB_PARAMS = {
    "host": "18.237.99.196",
    "port": 5433,
    "user": "yugabyte",
    "database": "hackathon_demo",
    "password": os.getenv("PGPASSWORD"),   # expects PGPASSWORD to be set
    "application_name": "slow-query-bench",
}

# ---------------------------------------------------------------------------
# Inefficient queries (exactly the ones we discussed earlier)
# ---------------------------------------------------------------------------
QUERIES = [
    # 1
    """
    SELECT  p.product_id,
            p.name,
            (SELECT SUM(oi.qty)
             FROM   order_items oi
             WHERE  oi.product_id = p.product_id) AS total_qty_sold
    FROM    products p;
    """,
    # 2
    "SELECT * FROM orders WHERE DATE(order_ts) = CURRENT_DATE - INTERVAL '1 day';",
    # 3
    "SELECT product_id, name FROM products WHERE name ILIKE '%phone%';",
    # 4
    """
    SELECT p.product_id, p.name
    FROM   products  p
    WHERE  p.product_id NOT IN (
              SELECT i.product_id
              FROM   inventory i
              WHERE  i.in_stock_qty > 0
          );
    """,
    # 5
    """
    SELECT c.username, p.name
    FROM   customers c, products p
    WHERE  c.created_at > now() - INTERVAL '7 days';
    """,
    # 6
    "SELECT order_id FROM orders ORDER BY RANDOM() LIMIT 10;",
    # 7
    "SELECT * FROM addresses WHERE city = 'San Francisco' OR state = 'CA';",
    # 8
    """
    SELECT  c.customer_id,
            c.username,
            (SELECT o.status
             FROM   orders o
             WHERE  o.customer_id = c.customer_id
             ORDER  BY o.order_ts DESC
             LIMIT  1) AS latest_status
    FROM    customers c;
    """,
    # 9
    """
    SELECT p.product_id, s.name, ps.lead_days
    FROM   product_suppliers ps
    JOIN   products  p ON p.product_id::text = ps.product_id::text
    JOIN   suppliers s ON s.supplier_id     = ps.supplier_id;
    """,
    # 10
    """
    SELECT DISTINCT ON (customer_id) customer_id, order_id, order_ts
    FROM   orders
    ORDER  BY customer_id, order_ts DESC;
    """,
]

RUNS_PER_QUERY = 10


def main() -> None:
    # -----------------------------------------------------------------------
    # Establish connection (autocommit off; we won't mutate data)
    # -----------------------------------------------------------------------
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            print(f"Connected to {DB_PARAMS['database']} on {DB_PARAMS['host']}:{DB_PARAMS['port']}\n")

            cur.execute("SET search_path TO demo;")

            for idx, sql in enumerate(QUERIES, start=1):
                print(f"Query {idx:02d}: running {RUNS_PER_QUERY} iterations ...")
                for run in range(1, RUNS_PER_QUERY + 1):
                    t0 = time.perf_counter()
                    cur.execute(sql)
                    _ = cur.fetchall()  # pull all rows so timing includes fetch cost
                    elapsed = time.perf_counter() - t0
                    print(f"  run {run:02d}: {elapsed:.3f} s")
                print()

    print("All done.")


if __name__ == "__main__":
    main()
