# Verifier image: Python only, no Hermes. Built from the task's tests/ directory, so the hidden
# checks exist only here, never in the agent's image. Harbor uploads the collected artifacts
# (/app and /logs/artifacts) and runs /tests/test.sh.
FROM python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
COPY . /tests/
RUN chmod +x /tests/test.sh
WORKDIR /tests
