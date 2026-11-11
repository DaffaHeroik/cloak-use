# cloak-use — MCP server (stdio) + CLI cb/cbd
# Butuh CDP endpoint (default: host di luar container via env CLOAK_HOST)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY cloak.py server.py auth.py vault.py auto_auth.py \
     session_manager.py session_guard.py gmail_reader.py todo_reader.py \
     flow.py setup_check.py ./
COPY bin/ ./bin/

# MCP stdio — browser CDP di host, arahkan lewat env saat run:
#   docker run -i --rm \
#     -e CLOAK_HOST=host.docker.internal -e CLOAK_PORT=9222 \
#     cloak-use serve
CMD ["python3", "server.py", "serve"]
