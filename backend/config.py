import os
import json
import logging
import boto3

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OpenAI Configuration
api_key_json = os.getenv("OPENAI_API_KEY")
if not api_key_json:
    raise RuntimeError("Environment variable OPENAI_API_KEY is not set")

try:
    api_key = json.loads(api_key_json)["OPENAI_API_KEY"]
except (json.JSONDecodeError, KeyError):
    raise RuntimeError("Invalid OPENAI_API_KEY format")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY is empty")

# Aurora Database Configuration
db_params = {
    "host": "kfranz-hackathon-instance-1.cl8cgsi0c707.us-west-2.rds.amazonaws.com",
    "port": 5432,
    "user": "appuser",
    "password": "Password#123",
    "database": "postgres",
    "sslmode": "require"
}

# Customer Database Configuration (Yugabyte)
customer_db_params = {
    "host": "18.237.99.196",
    "port": 5433,
    "user": "yugabyte",
    "database": "hackathon_demo",
}

# AWS RDS Data API Configuration
CLUSTER_ARN = "arn:aws:rds:us-west-2:990743404907:cluster:kfranz-hackathon"
SECRET_ARN = "arn:aws:secretsmanager:us-west-2:990743404907:secret:rds!cluster-b4676911-04f1-4cbc-a9d4-cb7c07d59908-AgoJSg"
DB_NAME = "postgres"

if not all([CLUSTER_ARN, SECRET_ARN, DB_NAME]):
    raise RuntimeError("Missing required environment variables: CLUSTER_ARN, SECRET_ARN, DB_NAME")

# AWS Clients
rds = boto3.client("rds-data", region_name="us-west-2")

# AI System Prompt
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