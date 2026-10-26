# syntax=docker/dockerfile:1
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 AS runtime
WORKDIR /opt/bonsai
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt,sharing=locked apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgomp1
ADD https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10787-73bfe6c/llama-prism-b10787-73bfe6c-bin-linux-cuda-12.8-x64.tar.gz /tmp/runtime.tar.gz
RUN echo "f61ac818da2c8cddc47d75c955b6f5bf821738138760842dd50413c5181cdfe1  /tmp/runtime.tar.gz" | sha256sum -c - && tar -xzf /tmp/runtime.tar.gz --strip-components=1 -C /opt/bonsai && rm /tmp/runtime.tar.gz && groupadd -g 1001 app && useradd -u 1001 -g app app
ENV LD_LIBRARY_PATH=/opt/bonsai
USER 1001:1001
EXPOSE 8080
ENTRYPOINT ["/opt/bonsai/llama-server"]
