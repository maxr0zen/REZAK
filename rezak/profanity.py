"""Mute Russian profanity using Whisper word timestamps."""
import json
import re


PROFANITY = re.compile(
    r'(?:\w*(?:пизд|ху[йеяиюё]|ебл|ебан|ебат|ебаш|ёб|ебуч|ебну|ебал)\w*|'
    r'бля(?:д\w*|ть|т|ха)?|сука|суки|мудак\w*|мудил\w*|гандон\w*)'
)


def mute_ranges(root, source_id):
    paths = sorted((root / 'transcripts').glob(source_id + '-*.json'),
                   key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        return []
    transcript = json.loads(paths[0].read_text(encoding='utf-8'))
    ranges = []
    for segment in transcript['segments']:
        for word in segment.get('words') or []:
            token = re.sub(r'[^а-яё]', '', word['text'].casefold())
            if PROFANITY.fullmatch(token):
                ranges.append((max(0, word['start_ms'] - 60), word['end_ms'] + 80))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def mute_filter(ranges, start_ms, end_ms):
    overlaps = [(max(start_ms, a), min(end_ms, b)) for a, b in ranges if a < end_ms and b > start_ms]
    if not overlaps:
        return ''
    tests = '+'.join(f'gte(t,{(a-start_ms)/1000:.3f})*lt(t,{(b-start_ms)/1000:.3f})' for a, b in overlaps)
    return f",volume=0:enable='{tests}'"
