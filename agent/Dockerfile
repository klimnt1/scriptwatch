FROM docker:24 AS docker-bin
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync curl \
  && rm -rf /var/lib/apt/lists/*
COPY --from=docker-bin /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py .
CMD ["python3", "agent.py"]
