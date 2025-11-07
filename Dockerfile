# Dockerfile for Streamlit expert-checker
FROM python:3.11-slim

WORKDIR /app
COPY . /app

# Install system deps needed by geopy
RUN apt-get update && apt-get install -y --no-install-recommends gcc libgeos-dev \
    && pip install --no-cache-dir streamlit requests geopy \
    && apt-get remove -y gcc && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.enableCORS=false"]
