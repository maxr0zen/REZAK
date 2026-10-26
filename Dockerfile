# syntax=docker/dockerfile:1
FROM python:3.11.14-slim-bookworm AS runtime
WORKDIR /app
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core
COPY requirements.lock /app/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r requirements.lock
RUN groupadd -g 1001 app && useradd -u 1001 -g app app && mkdir /data && chown app:app /data
COPY rezak /app/rezak
USER 1001:1001
ENTRYPOINT ["python", "-m", "rezak"]
CMD ["--help"]
