# Verifier image: Python and git, no Hermes. Built from the task's tests/ directory, so the
# hidden checks exist only here, never in the agent's image. Harbor uploads the collected
# artifacts (/app and /logs/artifacts) and runs /tests/test.sh. git is for tasks whose state is a
# repository; snapshots are owned by another user, hence safe.directory.
FROM python:3.14-slim-trixie@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
RUN apt-get -o Acquire::Retries=3 update  && apt-get -o Acquire::Retries=3 install -y --no-install-recommends git  && rm -rf /var/lib/apt/lists/*  && git config --system safe.directory '*'
COPY . /tests/
RUN chmod +x /tests/test.sh
WORKDIR /tests
