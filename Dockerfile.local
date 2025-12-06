FROM python:3.10-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# Install dependencies first (cached unless lockfile changes)
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project

# Then copy the rest of the code
COPY . /app
RUN uv sync --frozen

# Run the server
# Run the server
CMD ["uv", "run", "python", "agent_interface.py"]

# Build the docker
# docker build -t codereview-agent .
# run as
# docker run -it --rm -p 7860:7860 codereview-agent