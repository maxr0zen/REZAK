"""Reads a .env file into os.environ without overriding variables that are already set.

The studio service runs on the host while Docker Compose reads the same file for
the containers, so both sides need the provider settings from one place.
"""
import os
from pathlib import Path


def load_env_file(path):
    """Fills os.environ from a .env file and returns the names of the applied keys."""
    file = Path(path)
    if not file.is_file():
        return []
    applied = []
    for line in file.read_text(encoding='utf-8-sig').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        if stripped.startswith('export '):
            stripped = stripped[len('export '):].lstrip()
        key, _, value = stripped.partition('=')
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        applied.append(key)
    return applied
