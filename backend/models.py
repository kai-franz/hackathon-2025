from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

class QueryStatus(str, Enum):
    PENDING = "pending"
    ANALYZING_SCHEMA = "analyzing_schema"
    RUNNING_EXPLAIN = "running_explain"
    GENERATING_SUGGESTIONS = "generating_suggestions"
    COMPLETED = "completed"
    ERROR = "error"

class ExecutedQuery(BaseModel):
    query: str
    timestamp: str
    result_preview: Optional[str] = None

class QueryIn(BaseModel):
    sql: str

class QueryOut(BaseModel):
    optimized_query: str
    explanation: str = ""

class SlowQuery(BaseModel):
    id: str
    query: str
    suggestions: str
    status: QueryStatus = QueryStatus.PENDING
    current_step: Optional[str] = None
    progress_percentage: int = 0
    current_customer_query: Optional[str] = None
    executed_queries: List[ExecutedQuery] = []

class SlowQueriesResponse(BaseModel):
    queries: List[SlowQuery]
    session_id: str

class DebugInfo(BaseModel):
    message: str 