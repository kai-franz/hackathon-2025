import json
import re
import pprint
from openai import OpenAI
from config import api_key, SYSTEM_PROMPT, logger
from database import run_query_on_customer_db

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

def call_function(name: str, args: dict):
    """Handle function calls for OpenAI tool use"""
    try:
        args = json.loads(args)
    except json.JSONDecodeError:
        logger.error(f"Could not parse tool-call args: {args!r}")
        return f"Invalid arguments for tool {name}"

    if name == "run_customer_query":
        return run_query_on_customer_db(args["query"])
    return "Unknown function: " + name

def optimize_query(sql: str) -> tuple[str, str]:
    """
    Use OpenAI to optimize a SQL query.
    Returns (optimized_query, explanation) tuple.
    """
    logger.info(f"Optimizing query: {sql}")
    
    if not client.api_key:
        raise ValueError("OpenAI API key not configured")
    
    resp = client.responses.create(
        model="gpt-4.1",
        instructions=SYSTEM_PROMPT.strip(),
        input=sql,
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
    
    return optimized, explanation

def generate_query_suggestions(sql: str) -> str:
    """
    Generate performance suggestions for a SQL query using OpenAI with function calling.
    """
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

    return suggestions 