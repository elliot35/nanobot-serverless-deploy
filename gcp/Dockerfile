# Dockerfile for Google Cloud Run deployment of nanobot

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip to latest version
RUN pip install --upgrade pip setuptools wheel

# Copy requirements first for better caching
COPY gcp/requirements.txt .

# Install nanobot from GitHub (more reliable than PyPI)
RUN pip install --no-cache-dir git+https://github.com/HKUDS/nanobot.git@main

# Install remaining requirements
RUN pip install --no-cache-dir -r requirements.txt

# Verify nanobot is installed
RUN python -c "import nanobot; print('✓ nanobot installed successfully')" || \
    (echo "✗ Failed to import nanobot" && pip list | grep -i nanobot && exit 1)

# Copy application code
COPY . .

# Set Python path to include src directory
ENV PYTHONPATH=/app

# Verify nanobot can still be imported after copying code
RUN python -c "import nanobot; print('✓ nanobot import verified after code copy')" || \
    (echo "✗ nanobot import failed after code copy" && python -c "import sys; print('Python path:', sys.path)" && exit 1)

# Expose port (Cloud Run sets PORT env var)
EXPOSE 8080

# Run the FastAPI application
CMD ["python", "-m", "uvicorn", "gcp.main:app", "--host", "0.0.0.0", "--port", "8080"]
