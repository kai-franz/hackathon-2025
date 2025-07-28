import psycopg2
import psycopg2.extras
from config import rds, CLUSTER_ARN, SECRET_ARN, DB_NAME, customer_db_params, logger

def run_query_on_aurora(sql, params=None, tx=None):
    """Helper wrapping rds-data ExecuteStatement"""
    kwargs = dict(
        resourceArn=CLUSTER_ARN,
        secretArn=SECRET_ARN,
        database=DB_NAME,
        sql=sql,
        includeResultMetadata=True,
    )
    # If positional or named parameters were supplied, forward them
    if params:
        kwargs["parameters"] = params
    resp = rds.execute_statement(**kwargs)
    # SELECTs return "records"; DML (INSERT/UPDATE/DELETE) returns "numberOfRecordsUpdated"
    if "records" in resp:
        return resp["records"]
    return resp.get("numberOfRecordsUpdated")

def run_query_on_customer_db(sql: str):
    """
    Execute a read-only SQL query against the customer's Yugabyte (YSQL) database
    and return up to 100 rows as a list of dicts.

    The function refuses to run any non-read-only statement.
    """
    logger.info(f"Running query on customer database: {sql}")
    readonly_verbs = (
        "SELECT", "WITH", "EXPLAIN", "SHOW", "VALUES"
    )
    first_word = sql.strip().split()[0].upper()
    if first_word not in readonly_verbs:
        return "ERROR: Only read-only queries are allowed"

    conn = None
    try:
        conn = psycopg2.connect(**customer_db_params)
        # Make the session explicitly read‑only and autocommit so no transaction is kept open
        conn.set_session(readonly=True, autocommit=True)
        # Query user schemas and set search path
        with conn.cursor() as schema_cur:
            schema_cur.execute("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast', 'pg_temp_1', 'pg_toast_temp_1')
                ORDER BY schema_name
            """)
            user_schemas = [row[0] for row in schema_cur.fetchall()]
            
            if user_schemas:
                search_path = ', '.join(user_schemas + ['public'])
                schema_cur.execute(f"SET search_path TO {search_path}")
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchmany(100)  # limit result size
            return [dict(r) for r in rows]
    except Exception as e:
        # Error running the query. Report this back to the model.
        return str(e)
    finally:
        if conn is not None:
            conn.close() 