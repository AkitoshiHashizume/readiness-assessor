# Production Dockerfile for Google Cloud Run (AI Architecture Readiness Assessment Agent)
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    GOOGLE_GENAI_USE_VERTEXAI=true \
    GOOGLE_GENAI_USE_ENTERPRISE=true \
    GOOGLE_CLOUD_PROJECT=ai-readiness-assessor \
    GOOGLE_CLOUD_PROJECT_NUMBER=123456789012 \
    GOOGLE_CLOUD_LOCATION=us-central1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code & RAG knowledge base
COPY assessor/ ./assessor/
COPY sample_data/ ./sample_data/
COPY app.py cli.py ./

# Create non-root user for security best practices (Gate 1 compliance)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Launch Streamlit Web UI bound to Cloud Run $PORT
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true"]
