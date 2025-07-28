import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import re
import logging
import json
import psycopg2
import psycopg2.extras
import boto3
from typing import List
import datetime
import subprocess
import pprint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

api_key_json = os.getenv("OPENAI_API_KEY")
api_key = json.loads(api_key_json)["OPENAI_API_KEY"]
if not api_key:
    raise RuntimeError("Environment variable OPENAI_API_KEY is not set")

db_params = {
    "host": "kfranz-hackathon-instance-1.cl8cgsi0c707.us-west-2.rds.amazonaws.com",
    "port": 5432,
    "user": "appuser",
    "password": "Password#123",
    "database": "postgres",
    "sslmode": "require"
}

client = OpenAI(api_key=api_key)

app = FastAPI()

# Restrict in production: use your Vercel domain instead of "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

SYSTEM_PROMPT = """
You are a senior database performance engineer.

Rewrite the user's SQL so it is functionally equivalent but more performant.

Return the result wrapped in exactly the following XML tags (and nothing else):

<optimized_query>
...optimized SQL here...
</optimized_query>
<explanation>
...concise explanation of the changes here...
</explanation>
"""

class QueryIn(BaseModel):
    sql: str

class QueryOut(BaseModel):
    optimized_query: str
    explanation: str = ""

class SlowQuery(BaseModel):
    id: str
    query: str
    suggestions: str

class DebugInfo(BaseModel):
    message: str

rds = boto3.client("rds-data", region_name="us-west-2")
        
CLUSTER_ARN = "arn:aws:rds:us-west-2:990743404907:cluster:kfranz-hackathon"
SECRET_ARN = "arn:aws:secretsmanager:us-west-2:990743404907:secret:rds!cluster-b4676911-04f1-4cbc-a9d4-cb7c07d59908-AgoJSg"
DB_NAME = "postgres"

if not all([CLUSTER_ARN, SECRET_ARN, DB_NAME]):
    raise RuntimeError("Missing required environment variables: CLUSTER_ARN, SECRET_ARN, DB_NAME")

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

customer_db_params = {
    "host": "18.237.99.196",
    "port": 5433,
    "user": "yugabyte",
    "database": "hackathon_demo",
}

def call_function(name: str, args: dict):
    try:
        args = json.loads(args)
    except json.JSONDecodeError:
        logger.error(f"Could not parse tool-call args: {args!r}")
        return f"Invalid arguments for tool {name}"

    if name == "run_customer_query":
        return run_query_on_customer_db(args["query"])
    return "Unknown function: " + name

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
        raise ValueError("Only read-only queries are allowed")

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

@app.post("/optimize", response_model=QueryOut)
async def optimize(query: QueryIn):
    logger.info(f"Received query to optimize: {query.sql}")

    if not client.api_key:
        raise HTTPException(500, "OPENAI_API_KEY missing")
    try:
        resp = client.responses.create(
            model="gpt-4.1",
            instructions=SYSTEM_PROMPT.strip(),
            input=query.sql,
        )
        content = resp.output_text
        optimized_match = re.search(
            r"<optimized_query>(.*?)</optimized_query>", content, re.DOTALL | re.IGNORECASE
        )
        explanation_match = re.search(
            r"<explanation>(.*?)</explanation>", content, re.DOTALL | re.IGNORECASE
        )
        optimized = optimized_match.group(1).strip() if optimized_match else ""
        explanation = explanation_match.group(1).strip() if explanation_match else ""
        return {"optimized_query": optimized, "explanation": explanation}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/slow_queries", response_model=List[SlowQuery])
async def slow_queries(limit: int = 5):
    """
    Return the top `limit` slow queries from statements together with
    concise AI-generated tuning ideas.
    """
    logger.info("Fetching slow queries from Aurora")
    # --- pull slow queries from pg_stat_statements ---
    try:
        rows = run_query_on_aurora(
            f'''
            SELECT query, ai_suggestion
            FROM statements
            ORDER BY total_time DESC
            LIMIT {limit}
            ''',
        )
    except Exception as e:
        logger.error(f"Error fetching slow queries: {e}")
        raise HTTPException(500, f"Could not retrieve slow queries: {e}")

    # --- generate AI suggestions for each query ---
    slow_queries: List[SlowQuery] = []
    for i, row in enumerate(rows):
        logger.info(f"Processing query {i+1} of {len(rows)}: {row[0]['stringValue']}")
        sql = row[0]['stringValue']
        ai_suggestion = row[1]['stringValue'] if row[1].get('stringValue') else None
        
        # If we already have an AI suggestion stored, use it
        if ai_suggestion:
            suggestions = ai_suggestion
        else:
            # ----- Generate suggestion with OpenAI function calling -----
            instructions = (
                "You are a senior database performance engineer. "
                "Your job is to suggest performance optimizations for the user's SQL query."
                "Suggest query rewrites, index suggestions, hints, ANALYZE runs, etc. "
                "You may call the function `run_customer_query` to execute "
                "read-only SQL against the customer's Yugabyte database when helpful. "
                "Before answering, use run_customer_query to gather "
                "information about the customer's database. When you provide the response "
                "to the user, they should not have to run any queries to confirm your suggestions."
            )

            tools = [
                {
                    "name": "run_customer_query",
                    "type": "function",
                    "description": (
                        "Execute a read-only SQL query against the customer's "
                        "Yugabyte database."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "A SQL SELECT query."
                            }
                        },
                        "required": ["query"],
                    },
                }
            ]

            try:
                input_messages = [
                    {
                        "role": "user",
                        "content": sql,
                    }
                ]
                need_more_info = True

                while need_more_info:
                    logger.info(f"Input messages: {pprint.pformat(input_messages)}")
                    response = client.responses.create(
                        model="gpt-4.1",
                        instructions=instructions,
                        input=input_messages,
                        tools=tools,
                        tool_choice="auto",
                    )

                    logger.info(f"Response: {pprint.pformat(response.__dict__ if hasattr(response, '__dict__') else response)}")

                    need_more_info = False
                    for tool_call in response.output:
                        if tool_call.type != "function_call":
                            continue

                        result = call_function(tool_call.name, tool_call.arguments)
                        logger.info(f"Tool call result: {result}")
                        input_messages.append(tool_call)
                        input_messages.append({
                            "type": "function_call_output",
                            "call_id": tool_call.call_id,
                            "output": str(result),
                        })
                        need_more_info = True

                    if not need_more_info:
                        suggestions = response.output_text.strip()
                        logger.info(f"Suggestions: {suggestions}")
                        break

                # Store the AI suggestion back in Aurora
                try:
                    run_query_on_aurora(
                        """
                        UPDATE statements
                        SET ai_suggestion = :suggestions
                        WHERE query = :query
                        """,
                        params=[
                            {"name": "suggestions", "value": {"stringValue": suggestions}},
                            {"name": "query", "value": {"stringValue": sql}},
                        ],
                    )
                    logger.info("Stored AI suggestion for query in Aurora")
                except Exception as update_err:
                    logger.error(f"Error storing AI suggestion: {update_err}")
            except Exception as ai_err:
                logger.error(f"OpenAI error for query: {ai_err}")
                suggestions = "No suggestions available (AI error)."

        slow_queries.append(
            SlowQuery(id=str(len(slow_queries) + 1), query=sql.strip(), suggestions=suggestions)
        )

    return slow_queries

@app.get("/debug", response_model=DebugInfo)
async def debug():
    """
    Return debug information including system status and database connectivity.
    """
    logger.info("Debug endpoint called")
    
    debug_messages = []
    
    # Check current time
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    debug_messages.append(f"Server time: {current_time}")
    debug_messages.append("")
    
    # Check OpenAI API key
    if api_key:
        debug_messages.append("OpenAI API key: CONFIGURED")
    else:
        debug_messages.append("OpenAI API key: MISSING")
    debug_messages.append("")
    
    # Check database connection
    try:
        result = run_query_on_aurora("SELECT version();")
        if result:
            debug_messages.append("Database connection: SUCCESS")
            debug_messages.append(f"Database version: {result[0][0]['stringValue']}")
        else:
            debug_messages.append("Database connection: FAILED - no result")
    except Exception as db_error:
        debug_messages.append(f"Database connection: FAILED - {str(db_error)}")
    debug_messages.append("")
    
    # Check AWS credentials
    try:
        sts = boto3.client('sts')
        identity = sts.get_caller_identity()
        debug_messages.append(f"AWS credentials: CONFIGURED")
        debug_messages.append(f"Account: {identity.get('Account', 'Unknown')}")
    except Exception as aws_error:
        debug_messages.append(f"AWS credentials: ERROR - {str(aws_error)}")
    debug_messages.append("")
    
    # Environment info
    debug_messages.append(f"Environment variables: {len(os.environ)} total loaded")
    debug_messages.append("")

    # Check psql command availability
    try:
        result = subprocess.run(
            ['psql', '--version'], 
            capture_output=True, 
            text=True, 
            timeout=5
        )
        if result.returncode == 0:
            debug_messages.append(f"psql availability: AVAILABLE")
            debug_messages.append(f"Version: {result.stdout.strip()}")
            
            # Try to connect with psql to see typical error
            try:
                psql_result = subprocess.run(
                    ['psql', '-c', 'SELECT 1;'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if psql_result.returncode != 0:
                    error_msg = psql_result.stderr.strip()
                    if "/tmp/.s.PGSQL.5432" in error_msg or "connection to server" in error_msg:
                        debug_messages.append(f"psql connection test: EXPECTED LOCAL ERROR")
                        debug_messages.append(f"Error: {error_msg}")
                    else:
                        debug_messages.append(f"psql connection test: UNEXPECTED ERROR")
                        debug_messages.append(f"Error: {error_msg}")
                else:
                    debug_messages.append("psql connection test: UNEXPECTED SUCCESS (local connection)")
            except subprocess.TimeoutExpired:
                debug_messages.append("psql connection test: TIMEOUT")
            except Exception as psql_error:
                debug_messages.append(f"psql connection test: FAILED - {str(psql_error)}")
        else:
            debug_messages.append(f"psql availability: COMMAND FAILED")
            debug_messages.append(f"Error: {result.stderr.strip()}")
    except FileNotFoundError:
        debug_messages.append("psql availability: NOT FOUND")
    except subprocess.TimeoutExpired:
        debug_messages.append("psql availability: VERSION CHECK TIMEOUT")
    except Exception as psql_check_error:
        debug_messages.append(f"psql availability: CHECK FAILED - {str(psql_check_error)}")
    
    return DebugInfo(message="\n".join(debug_messages))
