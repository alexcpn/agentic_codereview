import redis
import os

def clear_history():
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6380))
    r = redis.Redis(host=redis_host, port=redis_port, db=0, decode_responses=True)

    print(f"Connecting to Redis at {redis_host}:{redis_port}...")
    
    # Find all keys matching the pattern
    keys = r.keys("review:*")
    
    if not keys:
        print("No history found to clear.")
        return

    print(f"Found {len(keys)} keys to delete.")
    for key in keys:
        print(f"Deleting {key}")
        r.delete(key)
    
    print("History cleared successfully.")

if __name__ == "__main__":
    clear_history()
