import os
import datetime
import subprocess
import boto3
import asyncio
import uuid
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import api_key, logger
from models import QueryIn, QueryOut, SlowQuery, SlowQueriesResponse, DebugInfo, QueryStatus, ExecutedQuery
from database import run_query_on_aurora
from ai_service import optimize_query, generate_query_suggestions, set_main_module

app = FastAPI()

# Task management for tracking AI generation progress
task_sessions: Dict[str, Dict[str, SlowQuery]] = {}
executor = ThreadPoolExecutor(max_workers=5)

# Restrict in production: use your Vercel domain instead of "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

def update_query_status(session_id: str, query_id: str, status: QueryStatus, current_step: str = None, progress: int = 0):
    """Update the status of a query in the task session"""
    if session_id in task_sessions and query_id in task_sessions[session_id]:
        task_sessions[session_id][query_id].status = status
        if current_step:
            task_sessions[session_id][query_id].current_step = current_step
        task_sessions[session_id][query_id].progress_percentage = progress
        logger.info(f"Updated query {query_id} status to {status} ({progress}%): {current_step}")

def update_query_customer_query(session_id: str, query_id: str, customer_query: str, timestamp: str):
    """Update the current customer query being executed"""
    if session_id in task_sessions and query_id in task_sessions[session_id]:
        task_sessions[session_id][query_id].current_customer_query = customer_query
        logger.info(f"Query {query_id} now executing: {customer_query[:100]}...")

def update_executed_query_result(session_id: str, query_id: str, result_preview: str):
    """Add executed query to the history with result preview"""
    if session_id in task_sessions and query_id in task_sessions[session_id]:
        current_query = task_sessions[session_id][query_id].current_customer_query
        if current_query:
            executed_query = ExecutedQuery(
                query=current_query,
                timestamp=datetime.datetime.now().strftime("%H:%M:%S"),
                result_preview=result_preview
            )
            task_sessions[session_id][query_id].executed_queries.append(executed_query)
            # Clear current query since it's now completed
            task_sessions[session_id][query_id].current_customer_query = None
            logger.info(f"Added executed query for {query_id}: {result_preview}")

# Set reference to this module for ai_service after functions are defined
import sys
set_main_module(sys.modules[__name__])

def generate_suggestions_with_progress(session_id: str, query_id: str, sql: str):
    """Generate AI suggestions with progress tracking - RUNS IN PARALLEL"""
    try:
        logger.info(f"🚀 PARALLEL TASK STARTED for query {query_id} in session {session_id}")
        
        # Check if session still exists
        if session_id not in task_sessions:
            logger.error(f"Session {session_id} disappeared before task started")
            return
            
        update_query_status(session_id, query_id, QueryStatus.GENERATING_SUGGESTIONS, "Analyzing query and generating suggestions", 50)
        
        # Generate the actual suggestions with session tracking
        logger.info(f"Starting AI generation for query {query_id}")
        suggestions = generate_query_suggestions(sql, session_id, query_id)
        logger.info(f"Completed AI generation for query {query_id}")
        
        # Update the query with results
        if session_id in task_sessions and query_id in task_sessions[session_id]:
            task_sessions[session_id][query_id].suggestions = suggestions
            update_query_status(session_id, query_id, QueryStatus.COMPLETED, "Analysis complete", 100)
            logger.info(f"✅ PARALLEL TASK COMPLETED for query {query_id}")
            
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
        else:
            logger.error(f"Session {session_id} or query {query_id} disappeared before completion")
        
    except Exception as e:
        logger.error(f"Error generating suggestions for query {query_id}: {e}", exc_info=True)
        if session_id in task_sessions and query_id in task_sessions[session_id]:
            update_query_status(session_id, query_id, QueryStatus.ERROR, f"Error: {str(e)}", 0)
        else:
            logger.error(f"Cannot update error status - session {session_id} or query {query_id} missing")

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

@app.get("/slow_queries", response_model=SlowQueriesResponse)
async def slow_queries(limit: int = 5):
    """
    Return the top `limit` slow queries with immediate response and parallel AI processing
    """
    logger.info("Fetching slow queries from Aurora")
    session_id = str(uuid.uuid4())
    
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

    # Create session for tracking
    task_sessions[session_id] = {}
    slow_queries_list: List[SlowQuery] = []
    
    # --- process queries and start parallel AI generation ---
    tasks_to_start = []
    
    for i, row in enumerate(rows):
        query_id = str(i + 1)
        sql = row[0]['stringValue']
        ai_suggestion = row[1]['stringValue'] if row[1].get('stringValue') else None
        
        # Create the slow query object
        if ai_suggestion:
            # Already have AI suggestion
            logger.info(f"Query {query_id} already has AI suggestion, marking as completed")
            slow_query = SlowQuery(
                id=query_id,
                query=sql.strip(),
                suggestions=ai_suggestion,
                status=QueryStatus.COMPLETED,
                current_step="Done analyzing",
                progress_percentage=100
            )
        else:
            # Need to generate AI suggestion
            logger.info(f"Query {query_id} needs AI suggestion, scheduling for processing")
            slow_query = SlowQuery(
                id=query_id,
                query=sql.strip(),
                suggestions="Thinking...",
                status=QueryStatus.ANALYZING_SCHEMA,
                current_step="Running in parallel...",
                progress_percentage=25
            )
            # Schedule background task for AI generation
            tasks_to_start.append((session_id, query_id, sql))
        
        task_sessions[session_id][query_id] = slow_query
        slow_queries_list.append(slow_query)
    
    # Start all AI generation tasks in parallel
    logger.info(f"Starting {len(tasks_to_start)} background tasks IN PARALLEL for session {session_id}")
    for task_session_id, query_id, sql in tasks_to_start:
        logger.info(f"Launching parallel task for query {query_id} in session {task_session_id}")
        executor.submit(generate_suggestions_with_progress, task_session_id, query_id, sql)
    
    logger.info(f"Created session {session_id} with {len(slow_queries_list)} queries")
    return SlowQueriesResponse(queries=slow_queries_list, session_id=session_id)

@app.get("/slow_queries/{session_id}/status", response_model=List[SlowQuery])
async def get_slow_queries_status(session_id: str):
    """Get the current status of slow queries for a session"""
    logger.info(f"Status request for session {session_id}")
    logger.info(f"Available sessions: {list(task_sessions.keys())}")
    
    if session_id not in task_sessions:
        logger.error(f"Session {session_id} not found in task_sessions")
        raise HTTPException(404, "Session not found")
    
    queries = list(task_sessions[session_id].values())
    logger.info(f"Returning {len(queries)} queries for session {session_id}")
    return queries

@app.delete("/slow_queries/{session_id}")
async def cleanup_session(session_id: str):
    """Clean up a completed session"""
    logger.info(f"Cleanup request for session {session_id}")
    
    if session_id not in task_sessions:
        logger.warning(f"Session {session_id} not found for cleanup")
        raise HTTPException(404, "Session not found")
    
    # Check if all queries are actually completed before cleanup
    queries = list(task_sessions[session_id].values())
    incomplete_queries = [q for q in queries if q.status not in ["completed", "error"]]
    
    if incomplete_queries:
        logger.warning(f"Session {session_id} has {len(incomplete_queries)} incomplete queries, refusing cleanup")
        return {"message": f"Session has {len(incomplete_queries)} incomplete queries, not cleaned up"}
    
    logger.info(f"Cleaning up session {session_id} with {len(queries)} completed queries")
    del task_sessions[session_id]
    return {"message": "Session cleaned up"}

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
