FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-warn-script-location -r requirements.txt

# Copy application code
COPY . /app

# Set working directory
WORKDIR /app

# Create non-root user
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# Expose metrics port (optional)
EXPOSE 8000

# Run the optimizer
CMD ["python", "optimizer.py"]