FROM hjr/hermes-base:ffc74885
COPY workspace/ /app/
# Evidence arrives one stage per turn (stages/ is outside the build context); see task.toml.
RUN mkdir -p /app/evidence /app/report
WORKDIR /app
