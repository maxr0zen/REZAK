"""Blur known stream overlays in source coordinates before reframing."""
from collections import defaultdict
from pathlib import Path
import subprocess
from functools import lru_cache

from pydantic import Field

from .plan import Interval, Region, StrictModel
from .media import ffmpeg


class AdZone(StrictModel):
    region: Region
    intervals: list[Interval] = Field(default_factory=list)


class AdMask(StrictModel):
    zones: list[AdZone]


def load_ad_mask(source: Path) -> AdMask:
    config = source.with_suffix('.ads.json')
    return AdMask.model_validate_json(config.read_text(encoding='utf-8-sig')) if config.exists() else AdMask(zones=[])


@lru_cache(maxsize=1)
def ad_templates():
    import cv2
    return [image for path in sorted(Path(__file__).with_name('ad_templates').glob('*.png'))
            if (image := cv2.imread(str(path))) is not None]


def detect_ad_regions(image):
    import cv2
    small = cv2.resize(image, (320,180), interpolation=cv2.INTER_AREA)
    boxes = [(0,0,94,60), (220,0,320,76), (0,124,94,180), (220,124,320,180)]
    regions = []
    for left,top,right,bottom in boxes:
        search = small[top:bottom,left:right]
        for template in ad_templates():
            h,w = template.shape[:2]
            if h > search.shape[0] or w > search.shape[1]:
                continue
            _, score, _, (x,y) = cv2.minMaxLoc(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED))
            if score >= .79:
                x,y = left+x,top+y
                regions.append((max(0,x-7),max(0,y-6),min(320,x+w+12),min(180,y+h+9)))
                break
    return regions


def detect_segment_ads(source, start_ms, end_ms):
    import numpy as np

    sample_ms = 250
    frame_bytes = 320 * 180 * 3
    intervals = defaultdict(list)
    previous_frame = None
    scene = 0
    for batch_start in range(start_ms, end_ms, 30_000):
        batch_end = min(batch_start + 30_000, end_ms)
        scan = subprocess.run([
            str(ffmpeg()), '-v', 'error', '-nostdin', '-ss', str(batch_start / 1000),
            '-i', str(source), '-t', str((batch_end - batch_start) / 1000), '-an',
            '-vf', 'fps=4:start_time=0:round=up,scale=320:180:flags=area', '-pix_fmt', 'bgr24',
            '-f', 'rawvideo', 'pipe:1',
        ], capture_output=True, timeout=120, check=True)
        for index in range(len(scan.stdout) // frame_bytes):
            offset = index * frame_bytes
            image = np.frombuffer(scan.stdout, dtype=np.uint8, count=frame_bytes,
                                  offset=offset).reshape(180, 320, 3)
            # Compare the central picture, excluding the animated corner overlays.
            center = image[35:145:4, 95:225:4].astype(np.int16)
            if previous_frame is not None and np.abs(center - previous_frame).mean() >= 30:
                scene += 1
            previous_frame = center
            left = batch_start + index * sample_ms
            right = min(left + sample_ms, batch_end)
            if right <= left:
                break
            for box in set(detect_ad_regions(image)):
                spans = intervals[box, scene]
                if spans and 0 <= left - spans[-1].end_ms <= 750:
                    spans[-1].end_ms = right
                else:
                    spans.append(Interval(start_ms=left, end_ms=right))
    # Require two adjacent positive frames and end at the last confirmation.
    # Extending past that frame can cover a webcam entering at an OBS cut.
    confirmed = defaultdict(list)
    for (box, _), spans in intervals.items():
        confirmed[box].extend(
            Interval(start_ms=span.start_ms, end_ms=span.end_ms-sample_ms)
            for span in spans if span.end_ms-span.start_ms > sample_ms
        )
    return AdMask(zones=[
        AdZone(region=Region(x=x/320, y=y/180, w=(r-x)/320, h=(b-y)/180), intervals=spans)
        for (x, y, r, b), spans in sorted(confirmed.items()) if spans
    ])


def ad_filters(mask, index, start_ms, end_ms, width, height):
    filters = []
    current = f'cut{index}'
    for zone_index, zone in enumerate(mask.zones):
        intervals = [(max(start_ms, item.start_ms), min(end_ms, item.end_ms)) for item in zone.intervals
                     if item.start_ms < end_ms and item.end_ms > start_ms]
        if zone.intervals and not intervals:
            continue
        region = zone.region
        x = int(region.x * width) // 2 * 2
        y = int(region.y * height) // 2 * 2
        right = min(width // 2 * 2, 2 * round((region.x + region.w) * width / 2))
        bottom = min(height // 2 * 2, 2 * round((region.y + region.h) * height / 2))
        w, h = right - x, bottom - y
        if min(w, h) < 4:
            continue
        label = f'ad{index}_{zone_index}'
        enable = ''
        if intervals:
            tests = [f'gte(t,{(left-start_ms)/1000})*lt(t,{(right-start_ms)/1000})' for left, right in intervals]
            enable = ":enable='" + '+'.join(tests) + "'"
        filters.extend([
            f'[{current}]split=2[{label}base][{label}region]',
            f'[{label}region]crop={w}:{h}:{x}:{y},scale=10:6:flags=area,'
            f'scale={w}:{h}:flags=bilinear,boxblur={min(w,h)//4}:3[{label}blur]',
            f'[{label}base][{label}blur]overlay={x}:{y}:shortest=1{enable}[{label}out]',
        ])
        current = f'{label}out'
    return filters, f'[{current}]'
