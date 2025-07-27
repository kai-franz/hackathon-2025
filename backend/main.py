import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import re
import logging
import json
import psycopg2
import boto3
from typing import List

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
    logger.info(f"Executing statement: {sql}")
    result = rds.execute_statement(**kwargs)["records"]
    logger.info(f"Done. Result: {result}")
    return result

@app.post("/optimize", response_model=QueryOut)
async def optimize(query: QueryIn):
    logger.info(f"Received query: {query.sql}")

    try:
        # Test database connection
        result = run_query_on_aurora("SELECT 1;")
        logger.info(f"Database connection test successful: {result}")
    except Exception as db_error:
        logger.info(f"Database connection test failed: {db_error}")

    if not client.api_key:
        raise HTTPException(500, "OPENAI_API_KEY missing")
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query.sql}
            ],
        )
        content = resp.choices[0].message.content
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
async def slow_queries(limit: int = 20):
    """
    Return the top `limit` slow queries from statements together with
    concise AI-generated tuning ideas.
    """
    logger.info("Fetching slow queries")
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
    for row in rows:
        sql = row[0]['stringValue']
        ai_suggestion = row[1]['stringValue'] if row[1].get('stringValue') else None
        
        # If we already have an AI suggestion stored, use it
        if ai_suggestion:
            suggestions = ai_suggestion
        else:
            # Generate new AI suggestion
            try:
                logger.info(f"Generating AI suggestion for query: {sql}")
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    temperature=0.3,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a senior database performance engineer. "
                                "Give a concise explanation of how to improve the query's performance."
                            ),
                        },
                        {"role": "user", "content": sql},
                    ],
                )
                suggestions = completion.choices[0].message.content.strip()
                # Store the AI suggestion back in Aurora
                try:
                    run_query_on_aurora(
                        f'''
                        UPDATE statements 
                        SET ai_suggestion = '{suggestions}' 
                        WHERE query = '{sql}'
                        ''',
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
