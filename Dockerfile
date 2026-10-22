# Glama (glama.ai/mcp/servers) builds this image, starts the stdio server,
# and runs initialize + tools/list. Those two methods are catalog-only and
# must not fetch quotes or need network. Stdlib only — no pip install.
FROM python:3.12-slim
WORKDIR /app
COPY . .
ENTRYPOINT ["python3", "scripts/mcp_server.py"]
