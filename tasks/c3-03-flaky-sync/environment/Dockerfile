FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
COPY mirror/ /srv/pricing-mirror/
RUN chmod +x /app/bin/sync.sh
WORKDIR /app
