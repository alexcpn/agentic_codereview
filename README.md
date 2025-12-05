---

title: Code Review Agentic AI based on MCP
emoji: 🛰️
colorFrom: indigo
colorTo: blue
sdk: docker
app_file: Dockerfile
pinned: false
---

# Agentic AI Code Review in Pure Python - No Agentic Framework

Agentic code review pipeline that plans, calls tools, and produces structured findings without any heavyweight framework. Implemented in plain Python using [uv](https://github.com/astral-sh/uv), [FastAPI](https://fastapi.tiangolo.com/), and a small footprint wrapper library [nmagents](https://github.com/alexcpn/noagent-ai). Deep code context comes from a Tree-Sitter-backed Model Context Protocol (MCP) server.

## Why this repo is interesting
- End-to-end AI review loop in a few hundred lines of Python (`code_review_agent.py`)
- Tool-augmented LLM via Tree-Sitter AST introspection from an MCP server
- Deterministic step planning/execution with JSON repair and YAML logs
- Works with OpenAI or any OpenAI-compatible endpoint (ollam,vllm)
- Ships as a FastAPI service, CLI helper, and Docker image

## How it works
- Fetch the PR diff, ask the LLM for a per-file review plan, then execute each step.
- MCP server ([codereview_mcp_server](https://github.com/alexcpn/codereview_mcp_server)) exposes AST tools (definitions, call-sites, docstrings) using [Tree-Sitter](https://tree-sitter.github.io/tree-sitter/).
- Minimal orchestration comes from [nmagents](https://github.com/alexcpn/noagent-ai) Command pattern: plan → optional tool calls → critique/patch suggestions → YAML logs.

Models are effective with very detailed prompts instead of one-liners. Illustration prompt is [prompts/code_review_prompts.txt](prompts/code_review_prompts.txt)  with context populated at place holders.

Results are good if a task can be broken into steps and each step executed in place. This keeps the context tight.

Models which gives good result are GPT 4.1 Nano, GPT 5 Nano. 

Also this will run with any OpenAI API comptatible model; Like ollam (with Microsoft phi3.5 model) and vllm (with Google gemma model) wtih a laptop GPU.

Note that these small models are really not that good with complex tasks like this.


### Core flow (excerpt from `code_review_agent.py`)


```python
file_diffs = git_utils.get_pr_diff_url(repo_url, pr_number)
response = call_llm_command.execute(context)                # plan steps
response_data, _ = parse_json_response_with_repair(...)     # repair/parse plan

tools = step.get("tools", [])
if tools:
    tool_outputs = await execute_step_tools(step, ast_tool_call_command)

step_context = load_prompt(diff_or_code_block=diff, tool_outputs=step.get("tool_results", ""))
step_response = call_llm_command.execute(step_context)      # execute each step
```

## Prerequisites
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) installed
- `.env` with `OPENAI_API_KEY=...`
- Running MCP server with AST tools (e.g., [codereview_mcp_server](https://github.com/alexcpn/codereview_mcp_server)) reachable at `CODE_AST_MCP_SERVER_URL`

## Setup
```bash
uv sync  # install dependencies from pyproject.toml
# create .env with OPENAI_API_KEY and optionally CODE_AST_MCP_SERVER_URL
```

## Start the Code Review MCP server
```bash
git clone https://github.com/alexcpn/codereview_mcp_server.git
cd codereview_mcp_server
uv run python http_server.py  # serves MCP at http://127.0.0.1:7860/mcp/
```

## Run the agent API
```bash
CODE_AST_MCP_SERVER_URL=http://127.0.0.1:7860/mcp/ \
uv run uvicorn code_review_agent:app --host 0.0.0.0 --port 8860
```

## Trigger a review
- CLI helper (default GET /review):
```bash
uv run python client.py --repo-url https://github.com/huggingface/accelerate --pr-number 3321
```
- Curl:
```bash
curl "http://127.0.0.1:8860/review?repo_url=https://github.com/huggingface/accelerate&pr_number=3321"
```
- Optional webhook-style POST: `python client.py --use-webhook ...` (see `client.py` for payload shape).

Logs land in `logs/` with per-step YAML outputs. See [sample_logs/](sample_logs/) for a captured run.

## Sample artifacts
- Plan produced by the LLM: [step](sample_logs/step_2_20251201103933.yaml)
- Tool result snippet from MCP: [output log](sample_logs/out_20251201103933_.log)
- Structured findings per step: [sample_logs/step_2_step1_done_20251201103933.yaml](sample_logs/step_2_step1_done_20251201103933.yaml), [sample_logs/step_2_step2_done_20251201103933.yaml](sample_logs/step_2_step2_done_20251201103933.yaml) etc

Example finding (truncated):
```yaml
Executive Summary:
- The current tests extensively cover the behavior of `infer_auto_device_map` with
  various configurations, especially relating to `reserve_max_layer`.
- The tests demonstrate that enabling or disabling `reserve_max_layer` influences
  how modules are allocated, especially in tight memory constraints.
- Minor inconsistencies exist between test expectations when toggling `reserve_max_layer`;
  notably, assumptions about offloading and buffer placement.
- No security issues identified; focus is on correctness and robustness of memory-based
  device mapping.
- The code primarily relies on size estimations, so the correctness heavily depends
  on accurate `module_sizes` calculations.
- "The tests\u2019 reliance on `try-except` for logs may mask potential issues, but\
  \ overall testing fulfills coverage adequately."
- The main risk is that future changes to `infer_auto_device_map` may invalidate assumptions,
  so explicit documentation and strict adherence to expected behaviors are advised.
Findings:
  ai_generated_smell: true
  category: maintainability
  code_snippet: 'device_map = infer_auto_device_map(model, max_memory={0: 200, 1:
    200}, reserve_max_layer=True)'
  cwe: N/A
  file: tests/test_modeling_utils.py
  fix:
```

## Docker
```bash
docker build -t codereview-agent .
docker run -it --rm -p 7860:7860 codereview-agent
```

## References
- [Model Context Protocol](https://github.com/modelcontextprotocol/specification)
- [Tree-Sitter](https://tree-sitter.github.io/tree-sitter/)
- [codereview_mcp_server](https://github.com/alexcpn/codereview_mcp_server)
- [nmagents (noagent-ai)](https://github.com/alexcpn/noagent-ai)
- [uv package manager](https://github.com/astral-sh/uv)


# Running Locally with Ray (Pure Ray)

This is the simplest way to run the agent without Kubernetes complexity.

## 1. Install Dependencies
Make sure you are in the project directory:
```bash
pip install -e .
```

## 2. Start Ray
Start a local Ray cluster instance:
```bash
uv run ray start --head
```
*Note: This starts Ray on your local machine. You can view the dashboard at http://127.0.0.1:8265*

## Run the code review mcp server
```bash
git clone https://github.com/alexcpn/codereview_mcp_server.git
cd codereview_mcp_server
uv run http_server.py
```

## 3. Run the Agent Service
Set your OpenAI API key and start the gRPC server:
```bash
export OPENAI_API_KEY=sk-YOUR_KEY
export AST_MCP_SERVER_URL=http://127.0.0.1:7860/mcp/ 
export RAY_ADDRESS="auto"  # Connects to the local Ray instance
uv run agent_interface.py
```

## 4. Run the Client
In a separate terminal, run the test client:
```bash
python test_client.py
```

## 5. Stop Ray
When you are done:
```bash
ray stop
```

# Running with persistent Redis DB

1. Run Redis with persistent storage:

```
docker run -d \
  -p 6380:6379 \
  --name redis-review \
  -v $(pwd)/redis-data:/data \
  redis \
  redis-server --appendonly yes
```

To delete older jobs

```
redis-cli --scan --pattern "review:*" | xargs redis-cli del
```


2. Start Ray 

Install Ray in your environment and start it

```bash
uv run ray start --head
```

2. Run the code review mcp server

```bash
git clone https://github.com/alexcpn/codereview_mcp_server.git
cd codereview_mcp_server
uv run http_server.py
```

## GUI Flow

Run the webserver

Note - see the .env (copy) file and create a .env file with the same variables but correct values

```
OPENAI_API_KEY=xxx
REDIS_PORT=6380
AST_MCP_SERVER_URL=http://127.0.0.1:7860/mcp/
RAY_ADDRESS="auto"
```

```
uv run web_server.py 
```
This will start the web server on port 8000


---


### CLI flow for Debuggging

1. Run the Agent Service


```bash

# give these in .env file or below

export OPENAI_API_KEY=sk-YOUR_KEY
export AST_MCP_SERVER_URL=http://127.0.0.1:7860/mcp/ 
export RAY_ADDRESS="auto"  # Connects to the local Ray instance
export REDIS_PORT=6380
uv run agent_interface.py


2. Run the redis reader

```bash
python redis_reader.py --repo-url https://github.com/huggingface/accelerate --pr-number 3321 --redis-port 6380
```

3. Run the Client
In a separate terminal, run the test client:
```bash
uv run  test_client.py
```
