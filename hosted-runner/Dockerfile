# Build context must be the repo root (see .dockerignore), so the image can see
# both deepdoc/ (installed as the deepdoc package) and hosted-runner/.
# Built for linux/arm64: Fargate Graviton is ~20% cheaper than x86 and the
# build host is Apple Silicon. Run via `hosted-runner/aws/deploy-image.sh`.
FROM python:3.12-slim

# git: clone target repos. Node.js >=18 + npm: `deepdoc deploy` shells out to
# `npx next build`. build-essential: safety net for any tree-sitter binding
# without a prebuilt wheel for the build platform.
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl build-essential ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir /app \
    && pip install --no-cache-dir -r /app/hosted-runner/requirements.txt \
    && pip install --no-cache-dir boto3

WORKDIR /app/hosted-runner
CMD ["python", "job.py"]
