# One image for the gateway, verifier and curator. Build from the repository root:
#   docker build -f deploy/Dockerfile -t lore-agents .
# The 0G Storage CLI is built here (stage `storage`), the same way shared/storage_cli/build.py builds it locally.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM golang:1.24-bookworm AS storage
# Must equal REVISION in shared/storage_cli/build.py (deploy/test_deploy.py checks).
ARG STORAGE_CLI_REVISION=bb5675461a96b654d3015c5522666ee8101cf810
WORKDIR /src
RUN git clone https://github.com/0gfoundation/0g-storage-client.git . && git checkout --detach "$STORAGE_CLI_REVISION"
COPY shared/storage_cli/main.go main.go
RUN go build -trimpath -o /lore-storage-client .

FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /opt/lore
COPY shared shared
COPY agents agents
RUN uv sync --project agents --locked --no-dev && uv pip install --python agents/.venv/bin/python ./shared
COPY --from=storage /lore-storage-client /usr/local/bin/lore-storage-client
COPY site site
COPY deploy/launch.py deploy/launch.py
ENV PATH=/opt/lore/agents/.venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1
WORKDIR /opt/lore/agents
ENTRYPOINT ["python", "/opt/lore/deploy/launch.py"]
