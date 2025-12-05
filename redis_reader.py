import argparse
import redis
import json
import os
import time

# example usage: 
# uv run python redis_reader.py --repo-url https://github.com/huggingface/accelerate --pr-number 3321 --redis-port 6380

def main():
    parser = argparse.ArgumentParser(description="Read code review events from Redis.")
    parser.add_argument("--repo-url", required=True, help="Full GitHub repository URL.")
    parser.add_argument("--pr-number", type=int, required=True, help="Pull request number.")
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"), help="Redis host.")
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", 6380)), help="Redis port.")
    parser.add_argument("--time-hash", help="Specific run time hash.")
    args = parser.parse_args()

    repo_name = args.repo_url.rstrip('/').split('/')[-1]
    r = redis.Redis(host=args.redis_host, port=args.redis_port, db=0, decode_responses=True)
    
    time_hash = args.time_hash
    if not time_hash:
        runs_key = f"review:runs:{repo_name}:{args.pr_number}"
        runs = r.smembers(runs_key)
        if not runs:
            print(f"No runs found for {repo_name} PR {args.pr_number}")
            return
        time_hash = sorted(list(runs), reverse=True)[0]
        print(f"No time hash provided, using latest run: {time_hash}")

    stream_key = f"review:stream:{repo_name}:{args.pr_number}:{time_hash}"

    print(f"Listening for events on {stream_key} at {args.redis_host}:{args.redis_port}...")
    
    # r is already initialized above
    last_id = "$"

    try:
        while True:
            # Block for 1000ms waiting for new messages
            streams = r.xread({stream_key: last_id}, count=1, block=1000)
            
            if not streams:
                continue

            for stream_name, messages in streams:
                for message_id, data in messages:
                    last_id = message_id
                    event_type = data.get("type")
                    file_path = data.get("file_path")
                    content = data.get("content")
                    
                    print(f"\n--- New Event: {event_type} for {file_path} ---")
                    
                    try:
                        parsed_content = json.loads(content)
                        if event_type == "plan":
                            print("Plan generated:")
                            print(json.dumps(parsed_content, indent=2))
                        elif event_type == "step":
                            step_name = data.get("step_name")
                            print(f"Step '{step_name}' completed:")
                            print(json.dumps(parsed_content, indent=2))
                        else:
                            print(content)
                    except json.JSONDecodeError:
                        print(content)
                    
                    print("-" * 50)

    except KeyboardInterrupt:
        print("\nStopping reader...")

if __name__ == "__main__":
    main()
