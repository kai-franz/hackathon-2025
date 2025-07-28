from pydantic import BaseModel
from typing import List

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