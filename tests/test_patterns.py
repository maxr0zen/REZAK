"""Паттерны монтажа: выбор по кадрам и геометрия под каждый паттерн."""
import numpy as np

from rezak import patterns
from rezak.patterns import FACE, SCREEN, SPLIT, apply_pattern, detect, pattern_of
from rezak.plan import EditPlan, Region, Segment


def fake_footage(monkeypatch, boxes, size=(540, 960)):
    """Frames with the given face boxes instead of a real video."""
    image = np.zeros((size[0], size[1], 3), dtype=np.uint8)
    monkeypatch.setattr('rezak.framing.frame', lambda *args, **kwargs: image)
    monkeypatch.setattr('rezak.framing.face_boxes', lambda frame, min_size=24: list(boxes))
    return image


def fake_footage_frames(monkeypatch, per_frame_boxes, size=(540, 960)):
    """Frames whose face boxes change from one sampled frame to the next."""
    image = np.zeros((size[0], size[1], 3), dtype=np.uint8)
    current = {'index': 0}

    def next_frame(*args, **kwargs):
        index = min(current['index'], len(per_frame_boxes) - 1)
        current['index'] += 1
        return image

    monkeypatch.setattr('rezak.framing.frame', next_frame)
    monkeypatch.setattr('rezak.framing.face_boxes',
                        lambda frame, min_size=24: list(per_frame_boxes[current['index'] - 1]))
    return image


def test_detect_uses_one_camera_crop_when_the_camera_fills_the_frame(monkeypatch):
    fake_footage(monkeypatch, [(300, 120, 200, 240)])
    pattern = detect('source.mp4', 0, 10000)
    assert pattern.kind == FACE
    assert pattern.secondary is None
    assert pattern.region is not None
    # A vertical crop keeps the face inside the frame.
    assert pattern.region.w * 960 / (pattern.region.h * 540) == 9 / 16


def test_detect_splits_when_a_small_camera_sits_in_the_corner(monkeypatch):
    fake_footage(monkeypatch, [(20, 20, 60, 70)])
    pattern = detect('source.mp4', 0, 10000)
    assert pattern.kind == SPLIT
    assert pattern.region.x == 0
    assert pattern.region.w < .2
    # The screen content is what is left of the picture beside the camera.
    assert pattern.secondary.x > .05
    assert pattern.secondary.w + pattern.region.w == 1


def test_detect_keeps_the_full_frame_without_a_face(monkeypatch):
    fake_footage(monkeypatch, [])
    pattern = detect('source.mp4', 0, 10000)
    assert pattern.kind == SCREEN
    assert pattern.region.w == 1 and pattern.region.h == 1


def test_detect_ignores_a_face_seen_in_a_single_frame(monkeypatch):
    """A rendered character that appears in one frame is not a camera."""
    fake_footage_frames(monkeypatch, [[(400, 200, 120, 120)], [], []])
    pattern = detect('source.mp4', 0, 10000)
    assert pattern.kind == SCREEN


def test_detect_keeps_the_screen_when_the_only_face_sits_in_the_middle(monkeypatch):
    """A face in the middle of a game screen is a character, not a webcam."""
    fake_footage(monkeypatch, [(400, 200, 120, 120)])
    pattern = detect('source.mp4', 0, 10000)
    assert pattern.kind == SCREEN


def test_detect_prefers_the_corner_camera_over_a_character(monkeypatch):
    """The webcam in the corner wins over a face-like shape in the scene."""
    fake_footage(monkeypatch, [(20, 20, 60, 70), (400, 200, 120, 120)])
    pattern = detect('source.mp4', 0, 10000)
    assert pattern.kind == SPLIT
    assert pattern.region.x == 0
    assert pattern.region.w < .2


def test_apply_pattern_writes_the_geometry_of_the_pattern():
    segment = Segment(start_ms=0, end_ms=5000, framing='fit')
    split = apply_pattern(segment, patterns.Pattern(
        SPLIT, Region(x=0.0, y=0.0, w=.2, h=.4), Region(x=.2, y=0.0, w=.8, h=1.0), 'тест'))
    assert split.framing == 'split'
    assert split.secondary_region.w == .8
    face = apply_pattern(segment, patterns.Pattern(
        FACE, Region(x=0.2, y=0.0, w=.6, h=1.0), None, 'тест'))
    assert face.framing == 'crop'
    assert face.secondary_region is None
    assert face.region.w == .6
    assert 'только вебка' in face.framing_note


def test_pattern_of_reads_the_planned_geometry():
    assert pattern_of(Segment(start_ms=0, end_ms=1000, framing='split',
                               region=Region(x=0, y=0, w=.3, h=.3),
                               secondary_region=Region(x=0, y=0, w=1, h=1))) == SPLIT
    assert pattern_of(Segment(start_ms=0, end_ms=1000, framing='crop',
                               region=Region(x=.2, y=0, w=.6, h=1.0))) == FACE
    assert pattern_of(Segment(start_ms=0, end_ms=1000, framing='crop',
                               region=Region(x=0, y=0, w=1, h=1))) == SCREEN


def test_resolve_keeps_manual_geometry_and_redecides_automatic_segments(monkeypatch):
    manual = Segment(start_ms=0, end_ms=5000, framing='crop',
                      region=Region(x=0.1, y=0.1, w=0.4, h=0.4),
                      framing_note='Область выбрана вручную')
    automatic = Segment(start_ms=5000, end_ms=10000, framing='fit',
                        framing_note='Авто: геометрия лица проверена на трёх кадрах.')
    plan = EditPlan(schema_version=1, source_id='demo', profile='vertical',
                    segments=[manual, automatic])
    monkeypatch.setattr(patterns, 'detect', lambda *args, **kwargs: patterns.Pattern(
        FACE, Region(x=0.2, y=0.0, w=0.5, h=0.8), None, 'тест'))
    resolved = patterns.resolve(plan, 'source.mp4')
    assert resolved.segments[0].region == Region(x=0.1, y=0.1, w=0.4, h=0.4)
    assert resolved.segments[0].framing == 'crop'
    assert resolved.segments[1].framing == 'crop'
    assert resolved.segments[1].region == Region(x=0.2, y=0.0, w=0.5, h=0.8)
    assert 'только вебка' in resolved.segments[1].framing_note
