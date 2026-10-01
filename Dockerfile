FROM python:3.12-slim-bookworm
COPY --from=docker.io/astral/uv:0.12.6 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HERMES_REPO=/opt/hermes-agent
ENV HERMES_SKILLS=/opt/hermes-home/.hermes/skills
ENV HOME=/opt/hermes-home
ENV HOST=0.0.0.0
ENV PATH="/opt/hermes-agent/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hermes-home/.hermes/skills

RUN git clone --depth 1 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent
WORKDIR /opt/hermes-agent
RUN uv venv /opt/hermes-agent/.venv \
    && uv sync --frozen --no-install-project \
    && uv pip install --python /opt/hermes-agent/.venv/bin/python --no-cache-dir --no-deps -e "."

WORKDIR /app
COPY aveyroni-agent-teams /app/aveyroni-agent-teams

WORKDIR /app/aveyroni-agent-teams/project-02-deal-origination
RUN sh ./scripts/install-hermes-skills.sh

EXPOSE 8791
CMD ["python", "chat/server.py"]
