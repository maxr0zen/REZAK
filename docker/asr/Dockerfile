# syntax=docker/dockerfile:1
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 AS runtime
WORKDIR /service
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked apt-get update && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.lock /service/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip pip install --require-hashes -r requirements.lock
RUN groupadd -g 1001 app && useradd -u 1001 -g app app && mkdir /models /data && chown app:app /models /data
COPY asr.py chunks.py /service/
USER 1001:1001
ENTRYPOINT ["python", "/service/asr.py"]
CMD ["--help"]
