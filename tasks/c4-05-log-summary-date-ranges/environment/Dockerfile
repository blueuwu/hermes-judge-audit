FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
COPY log_generator_deterministic.py /tmp/log_generator.py
RUN python3 /tmp/log_generator.py && rm /tmp/log_generator.py
WORKDIR /app
