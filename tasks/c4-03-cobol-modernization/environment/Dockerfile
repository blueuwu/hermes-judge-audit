FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
RUN apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends gnucobol3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
