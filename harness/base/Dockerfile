# hermes-eval-base: Hermes Agent at the audited commit, pre-installed so trials never run the
# upstream installer (which tracks main). Task images build FROM this image.
FROM python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d

ARG HERMES_SHA=ffc74885c5f6eb75f6c134fb4eef86d734066623

COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /usr/local/bin/uv

RUN apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      ca-certificates git ripgrep procps \
 && rm -rf /var/lib/apt/lists/*

# Exact commit, locked dependencies, no extras.
RUN git init -q /opt/hermes \
 && git -C /opt/hermes fetch -q --depth 1 https://github.com/NousResearch/hermes-agent "$HERMES_SHA" \
 && git -C /opt/hermes checkout -q FETCH_HEAD \
 && test "$(git -C /opt/hermes rev-parse HEAD)" = "$HERMES_SHA" \
 && cd /opt/hermes \
 && UV_PYTHON=/usr/local/bin/python3.14 uv sync --frozen --no-dev --no-cache \
 && ln -s /opt/hermes/.venv/bin/hermes /usr/local/bin/hermes \
 && echo "$HERMES_SHA" > /opt/hermes/HERMES_SHA

ENV HERMES_HOME=/tmp/hermes \
    PYTHONUNBUFFERED=1

WORKDIR /app
