#!/bin/bash
set -e

# Start Redis
echo "Starting Redis..."
redis-server --port 6380 &

# Start Ray
echo "Starting Ray..."
# We use --head to start a single node cluster
# We need to make sure it doesn't try to use too much memory if limited
uv run ray start --head --disable-usage-stats --port=6379 --dashboard-host=0.0.0.0

# Start MCP Server
echo "Starting MCP Server..."
cd codereview_mcp_server
uv run http_server.py &
MCP_PID=$!
cd ..

# Wait for MCP server to be ready (simple sleep for now, or check port)
sleep 5

# Set environment variables
export REDIS_PORT=6380
export AST_MCP_SERVER_URL=http://127.0.0.1:7860/mcp/
export RAY_ADDRESS="auto"

# Start Web Server
echo "Starting Web Server..."
# HF Spaces expects the app to listen on port 7860
uv run uvicorn web_server:app --host 0.0.0.0 --port 7860
