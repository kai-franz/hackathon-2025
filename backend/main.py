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
    allow_methods=["POST"],
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

@app.post("/optimize", response_model=QueryOut)
async def optimize(query: QueryIn):
    logger.info(f"Received query: {query.sql}")

    try:
        rds = boto3.client("rds-data", region_name="us-west-2")
        
        CLUSTER_ARN = "arn:aws:rds:us-west-2:990743404907:cluster:kfranz-hackathon"
        SECRET_ARN = "arn:aws:secretsmanager:us-west-2:990743404907:secret:rds!cluster-b4676911-04f1-4cbc-a9d4-cb7c07d59908-AgoJSg"
        DB_NAME = "postgres"
        
        if not all([CLUSTER_ARN, SECRET_ARN, DB_NAME]):
            raise RuntimeError("Missing required environment variables: CLUSTER_ARN, SECRET_ARN, DB_NAME")
        
        def run(sql, params=None, tx=None):
            """Helper wrapping rds-data ExecuteStatement"""
            kwargs = dict(
                resourceArn=CLUSTER_ARN,
                secretArn=SECRET_ARN,
                database=DB_NAME,
                sql=sql,
                parameters=params or [],
                includeResultMetadata=True,
            )
            return rds.execute_statement(**kwargs)["records"]
        
        # Test database connection
        result = run("SELECT 1")
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
