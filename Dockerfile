FROM python:3.12-slim

WORKDIR /app

# Install git for GitPython
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY scheduler.py .
COPY config.yml .

# Git configuration for submodule operations
RUN git config --global --add safe.directory /app/obsidian

CMD ["python", "scheduler.py"]
