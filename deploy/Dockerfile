# One image for the gateway, verifier and curator. Build from the repository root:
#   docker build -f deploy/Dockerfile -t lore-agents .
# Needs agents/ from P1 and a built shared/storage_cli/bin/lore-storage-client.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /opt/lore
COPY shared shared
COPY agents agents
RUN uv sync --project agents --locked --no-dev && uv pip install --python agents/.venv/bin/python ./shared
COPY shared/storage_cli/bin/lore-storage-client /usr/local/bin/lore-storage-client
COPY deploy/launch.py deploy/launch.py
ENV PATH=/opt/lore/agents/.venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1
WORKDIR /opt/lore/agents
ENTRYPOINT ["python", "/opt/lore/deploy/launch.py"]
