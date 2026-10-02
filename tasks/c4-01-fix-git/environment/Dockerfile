# Adapted from Terminal-Bench 2.0 `fix-git`. The site's GitHub repository no longer exists,
# so the repository (with the lost commit in its reflog) is taken from the upstream task
# image, pinned by digest. The patch files that upstream leaves in /app/resources are not
# copied: they are the expected answer.
FROM alexgshaw/fix-git@sha256:61e431c00c58df652287aadce5457634d9f9330cfdd153ebdf2802df0d540119 AS upstream

FROM hjr/hermes-base:ffc74885
COPY --from=upstream /app/personal-site /app/personal-site
COPY --from=upstream /root/.gitconfig /root/.gitconfig
RUN test "$(git -C /app/personal-site rev-parse --abbrev-ref HEAD)" = master
WORKDIR /app/personal-site
