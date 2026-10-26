#!/bin/sh
set -eu
test -n "$MODEL_SHA256"
if [ -f /models/model.gguf ] && [ -f /models/model.sha256 ] && [ "$(cat /models/model.sha256)" = "$MODEL_SHA256" ]; then
    echo 'Bonsai model already installed in Docker volume'
    exit 0
fi
if [ "${MODEL_PRECOPIED:-0}" != 1 ]; then
    cp "/source/$MODEL_FILE" /models/model.gguf.part
fi
printf '%s  %s\n' "$MODEL_SHA256" /models/model.gguf.part | sha256sum -c -
chmod 644 /models/model.gguf.part
mv /models/model.gguf.part /models/model.gguf
printf '%s' "$MODEL_SHA256" > /models/model.sha256
echo 'Bonsai model installed and verified'
