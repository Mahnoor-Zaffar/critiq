FROM python:3.12-slim

WORKDIR /code

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY .critiq.yml.sample ./
COPY README.md ./
COPY AGENTS.md ./

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "critiq-api"]
