FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
RUN chmod +x /app/bin/report.sh /app/tools/build_report.py \
 && ! command -v python3.9
WORKDIR /app
