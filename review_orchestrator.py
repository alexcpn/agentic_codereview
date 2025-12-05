import ray
import os
import logging as log
import yaml
from datetime import datetime
from typing import Any, List, Dict
import git_utils
from fastmcp import Client
from openai import OpenAI
from dotenv import load_dotenv
from nmagents.command import CallLLM, ToolCall, ToolList
from nmagents.utils import parse_json_response_with_repair, execute_step_tools
from pathlib import Path
import redis
import json

# Configure logging
log.basicConfig(level=log.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Load environment variables
load_dotenv()

# Constants
MAX_CONTEXT_LENGTH = 16385
COST_PER_TOKEN_INPUT = 0.10 / 10e6
COST_PER_TOKEN_OUTPUT = 0.40 / 10e6
MODEL_NAME = "gpt-4.1-nano"
FALLBACK_MODEL_NAME = os.getenv("JSON_REPAIR_MODEL", "gpt-4.1-nano")
FALLBACK_MAX_BUDGET = float(os.getenv("JSON_REPAIR_MAX_BUDGET", "0.2"))
AST_MCP_SERVER_URL = os.getenv("CODE_AST_MCP_SERVER_URL", "http://127.0.0.1:7860/mcp/")

if AST_MCP_SERVER_URL and not AST_MCP_SERVER_URL.endswith("/"):
    AST_MCP_SERVER_URL = AST_MCP_SERVER_URL + "/"

TEMPLATE_PATH = Path(__file__).parent / "prompts/code_review_prompts.txt"

def load_prompt(**placeholders) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    default_values = {
        "arch_notes_or_empty": "",
        "guidelines_list_or_link": "",
        "threat_model_or_empty": "",
        "perf_slos_or_empty": "",
        "tool_outputs": "",
        "diff_or_code_block": "",
    }
    merged = {**default_values, **placeholders}
    for key, value in merged.items():
        value_str = str(value)
        template = template.replace(f"{{{{{key}}}}}", value_str)
        template = template.replace(f"{{{key}}}", value_str)
    return template

@ray.remote
def process_file_review(file_path: str, diff: str, repo_url: str, pr_number: int, tool_schemas_content: str, step_schema_content: str, time_hash: str, redis_host: str, redis_port: int):
    import asyncio
    return asyncio.run(_process_file_review_async(file_path, diff, repo_url, pr_number, tool_schemas_content, step_schema_content, time_hash, redis_host, redis_port))

async def _process_file_review_async(file_path: str, diff: str, repo_url: str, pr_number: int, tool_schemas_content: str, step_schema_content: str, time_hash: str, redis_host: str, redis_port: int):
    log.info(f"Starting review for {file_path}")
    
    # Initialize Redis client
    # redis_host and redis_port are passed from the orchestrator
    redis_client = redis.Redis(host=redis_host, port=redis_port, db=0)
    repo_name = repo_url.rstrip('/').split('/')[-1]
    stream_key = f"review:stream:{repo_name}:{pr_number}:{time_hash}"
    runs_key = f"review:runs:{repo_name}:{pr_number}"
    
    # Add this run to the history
    try:
        redis_client.sadd(runs_key, time_hash)
    except Exception as e:
        log.error(f"Failed to add run to history: {e}")
    
    # Re-initialize clients inside the remote task
    api_key = os.getenv("OPENAI_API_KEY")
    openai_client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
    
    call_llm_command = CallLLM(openai_client, "Call the LLM", MODEL_NAME, COST_PER_TOKEN_INPUT, COST_PER_TOKEN_OUTPUT, 0.5)
    repair_llm_command = CallLLM(openai_client, "Repair YAML", FALLBACK_MODEL_NAME, COST_PER_TOKEN_INPUT, COST_PER_TOKEN_OUTPUT, FALLBACK_MAX_BUDGET)
    
    step_execution_results = []
    
    async with Client(AST_MCP_SERVER_URL) as ast_tool_client:
        ast_tool_call_command = ToolCall(ast_tool_client, "Call tool")
        
        main_context = f""" Your task today is Code Reivew. You are given the following '{pr_number}' to review from the repo '{repo_url}' 
        You have to first come up with a plan to review the code changes in the PR as a series of steps.
        Write the plan as per the following step schema: {step_schema_content}
        Make sure to follow the step schema format exactly  and output only JSON """
        
        context = main_context + f" Here is the file diff for {file_path}:\n{diff} for review\n" + \
            f"You have access to the following MCP tools to help you with your code review: {tool_schemas_content}"
            
        response = call_llm_command.execute(context)
        log.info(f"Plan generated for {file_path}")
        
        response_data, _ = parse_json_response_with_repair(
            response_text=response or "",
            schema_hint=step_schema_content,
            repair_command=repair_llm_command,
            context_label="plan",
        )
        
        # Save plan log
        safe_filename = file_path.replace("/", "_").replace("\\", "_")
        repo_name = repo_url.rstrip('/').split('/')[-1]
        job_dir = f"{repo_name}_PR{pr_number}_{time_hash}"
        logs_dir = Path("logs") / job_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        plan_log_path = logs_dir / f"plan_{safe_filename}.yaml"
        with open(plan_log_path, "w", encoding="utf-8") as f:
            yaml.dump(response_data, f)

        # Publish plan to Redis
        try:
            redis_client.xadd(stream_key, {
                "type": "plan",
                "file_path": file_path,
                "content": json.dumps(response_data)
            })
        except Exception as e:
            log.error(f"Failed to write plan to Redis: {e}")
        
        steps = response_data.get("steps", [])
        
        for index, step in enumerate(steps, start=1):
            name = step.get("name", "<unnamed>")
            step_description = step.get("description", "")
            
            tools = step.get("tools", [])
            if tools:
                log.info(f"Executing tools for step {name}: {tools}")
                tool_outputs = await execute_step_tools(step, ast_tool_call_command)
                for output in tool_outputs:
                    tool_result_context = load_prompt(repo_name=repo_url, brief_change_summary=step_description,
                                                diff_or_code_block=diff, tool_outputs=output)
                    step["tool_results"] = tool_result_context
            
            try:
                step_context = load_prompt(repo_name=repo_url, brief_change_summary=step_description,
                                           diff_or_code_block=diff, tool_outputs=step.get("tool_results", ""))
                
                step_response = call_llm_command.execute(step_context)
                
                step_data, _ = parse_json_response_with_repair(
                    response_text=step_response or "",
                    schema_hint="",
                    repair_command=repair_llm_command,
                    context_label=f"step {name}",
                )
                
                # Save step log
                step_log_path = logs_dir / f"step_{name}_{safe_filename}.yaml"
                with open(step_log_path, "w", encoding="utf-8") as f:
                    yaml.dump(step_data, f)
                
                step_execution_results.append({
                    "step_name": name,
                    "result": step_data
                })

                # Publish step result to Redis
                try:
                    redis_client.xadd(stream_key, {
                        "type": "step",
                        "file_path": file_path,
                        "step_name": name,
                        "content": json.dumps(step_data)
                    })
                except Exception as e:
                    log.error(f"Failed to write step to Redis: {e}")
                
            except Exception as e:
                log.error(f"Failed to execute step {name} for {file_path}: {e}")
                step_execution_results.append({
                    "step_name": name,
                    "error": str(e)
                })
                break
                
    return {
        "file_path": file_path,
        "results": step_execution_results
    }

class CodeReviewOrchestrator:
    def __init__(self):
        # Initialize Ray
        # Check if running in a cluster or local
        ray_address = os.getenv("RAY_ADDRESS")
        if ray_address:
            ray.init(address=ray_address, ignore_reinit_error=True)
        else:
            ray.init(ignore_reinit_error=True)
        
    async def review_pr_stream(self, repo_url: str, pr_number: int, time_hash: str = None):
        log.info(f"Orchestrating review for {repo_url} PR #{pr_number}")
        
        # Get diffs
        file_diffs = git_utils.get_pr_diff_url(repo_url, pr_number)
        
        # Get tool schemas (need to do this once)
        async with Client(AST_MCP_SERVER_URL) as ast_tool_client:
            ast_tool_list_command = ToolList(ast_tool_client, "List tools")
            tool_schemas_content = await ast_tool_list_command.execute(None)
            
        sample_step_schema_file = "schemas/steps_schema.json"
        with open(sample_step_schema_file, "r", encoding="utf-8") as f:
            step_schema_content = f.read()
            
        if not time_hash:
            time_hash = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Redis config to pass to workers
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", 6380))

        # Launch Ray tasks
        pending_futures = []
        for file_path, diff in file_diffs.items():
            pending_futures.append(process_file_review.remote(
                file_path, diff, repo_url, pr_number, tool_schemas_content, step_schema_content, time_hash, redis_host, redis_port
            ))
            
        # Collect all reviews for final summary
        all_reviews_context = ""
        
        # Process results as they complete
        while pending_futures:
            done_futures, pending_futures = ray.wait(pending_futures)
            for future in done_futures:
                try:
                    result = await future
                    
                    # Format the result for this file
                    file_summary = f"File: {result['file_path']}\n"
                    for step in result['results']:
                        if 'error' in step:
                            file_summary += f"- {step['step_name']}: [Error] {step['error']}\n"
                        else:
                            file_summary += f"- {step['step_name']}: {step['result']}\n"
                    
                    all_reviews_context += file_summary + "\n" + "-"*40 + "\n"
                    
                    yield {
                        "file_path": result['file_path'],
                        "comment": file_summary
                    }
                except Exception as e:
                    log.error(f"Error processing result from ray: {e}")
                    yield {
                        "file_path": "system",
                        "comment": f"Error: {str(e)}"
                    }
        
        # Generate Final Consolidated Summary
        log.info("Generating consolidated PR summary...")
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            openai_client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
            summary_llm_command = CallLLM(openai_client, "Summarize PR", MODEL_NAME, COST_PER_TOKEN_INPUT, COST_PER_TOKEN_OUTPUT, 0.5)
            
            summary_prompt = f"""
            You are a Principal Software Engineer. 
            Review the following code review results for PR #{pr_number} in {repo_url}.
            
            Aggregated Reviews:
            {all_reviews_context}
            
            Please provide a concise Executive Summary of the PR.
            1. Highlight the most critical issues found across all files.
            2. Identify any recurring patterns or code quality concerns.
            3. Provide a final recommendation (Merge, Request Changes, etc.).
            """
            
            final_summary = summary_llm_command.execute(summary_prompt)
            
            yield {
                "file_path": "PR_SUMMARY",
                "comment": f"# Consolidated PR Summary\n\n{final_summary}"
            }
            
            # Save summary log
            logs_dir = Path("logs") / f"{repo_url.rstrip('/').split('/')[-1]}_PR{pr_number}_{time_hash}"
            with open(logs_dir / "pr_summary.md", "w", encoding="utf-8") as f:
                f.write(final_summary)
                
        except Exception as e:
            log.error(f"Failed to generate final summary: {e}")
            yield {
                "file_path": "PR_SUMMARY",
                "comment": f"Failed to generate summary: {e}"
            }
