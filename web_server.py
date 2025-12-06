import os
import json
import asyncio
import redis.asyncio as redis
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from review_orchestrator import CodeReviewOrchestrator
from pydantic import BaseModel
from load_dotenv import load_dotenv
load_dotenv()
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Initialize Orchestrator
orchestrator = CodeReviewOrchestrator()

class ReviewRequest(BaseModel):
    repo_url: str
    pr_number: int
    openai_api_key: str | None = None
    mcp_server_url: str | None = None

class MCPRequest(BaseModel):
    mcp_server_url: str

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/list-tools")
async def list_tools(request: MCPRequest):
    from fastmcp import Client
    from nmagents.command import ToolList
    
    try:
        # Ensure URL ends with /
        url = request.mcp_server_url
        if not url.endswith("/"):
            url = url + "/"
            
        async with Client(url) as client:
            # We can't easily use ToolList command here as it returns a formatted string
            # We'll use the client directly to list tools if possible, or parse the output
            # fastmcp client doesn't expose list_tools directly in a simple way without calling the server
            # But nmagents ToolList does exactly that.
            
            tool_list_command = ToolList(client, "List tools")
            tools_description = await tool_list_command.execute(None)
            return {"status": "success", "tools": tools_description}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/review")
async def trigger_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    # Trigger the review in the background
    # We need to wrap the async generator to consume it, otherwise it won't run
    # We need to get the time_hash to return it, but the orchestrator generates it.
    # For now, we will generate it here and pass it, or just return a "latest" indicator.
    # Better: Orchestrator's review_pr_stream generates it. We can't easily get it back from a background task.
    # Solution: We will generate time_hash here and pass it to orchestrator (need to update orchestrator signature).
    
    from datetime import datetime
    time_hash = datetime.now().strftime("%Y%m%d%H%M%S")
    
    # Add run to history immediately
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6380))
    r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
    repo_name = request.repo_url.rstrip('/').split('/')[-1]
    runs_key = f"review:runs:{repo_name}:{request.pr_number}"
    await r.sadd(runs_key, time_hash)
    await r.close()

    background_tasks.add_task(run_review, request.repo_url, request.pr_number, time_hash, request.openai_api_key, request.mcp_server_url)
    
    return {"status": "Review started", "time_hash": time_hash, "stream_url": f"/stream/{repo_name}/{request.pr_number}/{time_hash}"}

async def run_review(repo_url: str, pr_number: int, time_hash: str, api_key: str | None = None, mcp_server_url: str | None = None):
    # Consume the generator to ensure it runs
    # Note: We need to update orchestrator.review_pr_stream to accept time_hash
    async for _ in orchestrator.review_pr_stream(repo_url, pr_number, time_hash, api_key, mcp_server_url):
        pass

@app.get("/runs/{repo_name}/{pr_number}")
async def list_runs(repo_name: str, pr_number: int):
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6380))
    r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
    runs_key = f"review:runs:{repo_name}:{pr_number}"
    
    try:
        runs = await r.smembers(runs_key)
        return {"runs": sorted(list(runs), reverse=True)}
    finally:
        await r.close()

@app.get("/runs")
async def list_all_runs():
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6380))
    r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
    
    try:
        keys = await r.keys("review:runs:*:*")
        all_runs = []
        for key in keys:
            # key format: review:runs:repo_name:pr_number
            parts = key.split(":")
            if len(parts) >= 4:
                repo_name = parts[2]
                pr_number = parts[3]
                runs = await r.smembers(key)
                for run in runs:
                    all_runs.append({
                        "repo_name": repo_name,
                        "pr_number": pr_number,
                        "time_hash": run
                    })
        
        # Sort by time_hash descending
        all_runs.sort(key=lambda x: x["time_hash"], reverse=True)
        return {"runs": all_runs}
    finally:
        await r.close()

@app.get("/stream/{repo_name}/{pr_number}/{time_hash}")
async def stream_events(repo_name: str, pr_number: int, time_hash: str):
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6380))
    r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)
    stream_key = f"review:stream:{repo_name}:{pr_number}:{time_hash}"
    
    async def event_generator():
        last_id = "0-0" # Start from beginning
        try:
            while True:
                # Read new messages
                streams = await r.xread({stream_key: last_id}, count=1, block=1000)
                
                if not streams:
                    # Send a keep-alive comment to prevent timeout
                    yield ": keep-alive\n\n"
                    continue

                for stream_name, messages in streams:
                    for message_id, data in messages:
                        last_id = message_id
                        # Format as SSE
                        yield f"data: {json.dumps(data)}\n\n"
                        
        except asyncio.CancelledError:
            print("Stream cancelled")
        finally:
            await r.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
