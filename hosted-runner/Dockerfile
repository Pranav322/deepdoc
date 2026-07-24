# Build context must be the repo root (not hosted-runner/), so this image
# can see both deepdoc/ (installed as the deepdoc package) and hosted-runner/
# (the FastAPI service). Built from local source, not PyPI — see AGENTS.md
# "Hosted-generation harness" section for why.
FROM python:3.12-slim

# git: needed to clone target repos. Node.js >=18 + npm: `deepdoc deploy`
# shells out to `npx next build`. build-essential: safety net for any
# tree-sitter binding without a prebuilt wheel for the build platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir /app \
    && pip install --no-cache-dir -r /app/hosted-runner/requirements.txt

WORKDIR /app/hosted-runner
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
