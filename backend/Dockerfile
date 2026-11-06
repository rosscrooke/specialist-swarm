FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
# Chromium for server-side PDF export, in a path the app user can read.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && .venv/bin/playwright install --with-deps chromium
COPY . .
USER 1000:1000
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"
CMD [".venv/bin/fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
