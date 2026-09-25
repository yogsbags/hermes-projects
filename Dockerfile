FROM ghcr.io/astral-sh/uv:0.11.6-python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HERMES_REPO=/opt/hermes-agent
ENV HERMES_SKILLS=/opt/hermes-home/.hermes/skills
ENV HOME=/opt/hermes-home
ENV HOST=0.0.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/hermes-home/.hermes/skills

RUN git clone --depth 1 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --no-cache /opt/hermes-agent
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY aveyroni-agent-teams /app/aveyroni-agent-teams

WORKDIR /app/aveyroni-agent-teams/project-02-deal-origination
RUN ./scripts/install-hermes-skills.sh

EXPOSE 8791
CMD ["python", "chat/server.py"]
