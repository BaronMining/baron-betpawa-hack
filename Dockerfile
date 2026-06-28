FROM python:3.11.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY config.py betpawa_login.py hash_analyzer.py predictor.py bot.py ./

# Health check
EXPOSE 10000

CMD ["python", "bot.py"]
