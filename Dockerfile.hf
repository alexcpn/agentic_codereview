FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    redis-server \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project

COPY . /app
RUN uv sync --frozen

# Clone MCP server
RUN git clone https://github.com/alexcpn/codereview_mcp_server.git

# Make startup script executable
RUN chmod +x start_hf.sh

# Create a user to run the app (optional but good practice, though HF often runs as 1000)
# For simplicity in this setup, we'll run as root or default user, 
# but we need to make sure we can write to directories if needed.
# HF Spaces usually run as user 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Expose the port (HF Spaces expects 7860)
EXPOSE 7860

CMD ["./start_hf.sh"]
