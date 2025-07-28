import os
import datetime
import subprocess
import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List

from config import api_key, logger
from models import QueryIn, QueryOut, SlowQuery, DebugInfo
from database import run_query_on_aurora
from ai_service import optimize_query, generate_query_suggestions

app = FastAPI()

# Restrict in production: use your Vercel domain instead of "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

@app.post("/optimize", response_model=QueryOut)
async def optimize(query: QueryIn):
    """Optimize a SQL query using AI"""
    logger.info(f"Received query to optimize: {query.sql}")

    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY missing")
    
    try:
        optimized, explanation = optimize_query(query.sql)
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
            try:
                suggestions = generate_query_suggestions(sql)
                
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
