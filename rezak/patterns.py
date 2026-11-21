"""Montage pattern chosen from what the footage actually shows.

The reference clip splits the picture into a webcam panel and a gameplay panel.
That split only makes sense while the screen carries the story. When the source
is a talking head, or a camera that fills the whole frame, the montage keeps a
single camera crop: splitting a full-screen webcam puts a cropped camera above
the very same camera, which is the artefact this module prevents.

Three patterns:
 - split  - the screen matters: webcam panel on top, screen content below.
 - face   - only the person matters: one full-frame camera crop.
 - screen - there is no camera: the content fills the frame.
"""
from dataclasses import dataclass

from .plan import Region

SPLIT = 'split'
FACE = 'face'
SCREEN = 'screen'

LABELS = {SPLIT: 'сплит вебка/игра', FACE: 'только вебка', SCREEN: 'только экран'}

# A face wider than this share of the frame means the camera fills the picture.
CAMERA_WIDTH = .16
# A camera box face sits within this share of the frame edge.
CORNER_EDGE = .25
# A camera box leaves no room for the screen content.
MIN_SCREEN = .25
# How close two detections must be to count as the same face.
SAME_CENTRE = .08
SAME_SIZE = 1.5
# The face is looked for on a wider frame: a camera box is tiny in a preview.
DETECTION_WIDTH = 1600


@dataclass(frozen=True)
class Pattern:
    kind: str
    region: Region | None = None
    secondary: Region | None = None
    note: str = ''

    @property
    def label(self) -> str:
        return LABELS.get(self.kind, self.kind)


def pattern_of(segment) -> str:
    """The pattern a planned segment describes."""
    if segment.framing == 'split':
        return SPLIT
    region = getattr(segment, 'region', None)
    if region is None or (region.w >= .98 and region.h >= .98):
        return SCREEN
    return FACE


def _same_face(first, second, width, height):
    if max(first[2], second[2]) / max(1, min(first[2], second[2])) > SAME_SIZE:
        return False
    dx = abs((first[0] + first[2] / 2) - (second[0] + second[2] / 2)) / width
    dy = abs((first[1] + first[3] / 2) - (second[1] + second[3] / 2)) / height
    return dx < SAME_CENTRE and dy < SAME_CENTRE


def _median_box(boxes):
    """Stable box for a face seen in several frames."""
    count = len(boxes)
    middle = count // 2
    centres_x = sorted(box[0] + box[2] / 2 for box in boxes)
    centres_y = sorted(box[1] + box[3] / 2 for box in boxes)
    widths = sorted(box[2] for box in boxes)
    heights = sorted(box[3] for box in boxes)
    return (centres_x[middle] - widths[middle] / 2, centres_y[middle] - heights[middle] / 2,
            widths[middle], heights[middle])


def _camera_box(x, y, w, h, width, height):
    """Portrait camera view around a detected face."""
    left = max(0, x - w * .65)
    top = max(0, y - h * .6)
    right = min(width, x + w * 1.65)
    bottom = min(height, y + h * 2.5)
    return Region(x=left / width, y=top / height,
                  w=(right - left) / width, h=(bottom - top) / height)


def _vertical_camera(centre_x, width, height):
    """A vertical crop of the whole frame, centred on the face.

    The picture of a camera that fills the frame is cropped to 9:16 by losing
    the sides only: the full height stays, so the head is never cut off.
    """
    crop_width = height * 9 / 16
    if crop_width >= width:
        return Region(x=0, y=0, w=1, h=1)
    left = min(max(0, centre_x - crop_width / 2), width - crop_width)
    return Region(x=left / width, y=0, w=crop_width / width, h=1)


def _screen_box(camera):
    """The screen content that goes next to a camera box.

    A camera that sits against an edge of the picture hides the band behind it,
    so that band alone is the screen content. A camera that floats inside the
    picture hides nothing: the whole frame stays the screen content.
    """
    right = camera.x + camera.w
    bottom = camera.y + camera.h
    vertical = []
    horizontal = []
    if camera.x <= .02 and right < 1:
        vertical.append(Region(x=right, y=0, w=1 - right, h=1))
    if right >= .98 and camera.x > 0:
        vertical.append(Region(x=0, y=0, w=camera.x, h=1))
    if camera.y <= .02 and bottom < 1:
        horizontal.append(Region(x=0, y=bottom, w=1, h=1 - bottom))
    if bottom >= .98 and camera.y > 0:
        horizontal.append(Region(x=0, y=0, w=1, h=camera.y))
    options = vertical or horizontal
    if not options:
        return Region(x=0, y=0, w=1, h=1)
    return max(options, key=lambda region: region.w * region.h)


def _in_corner(box, width, height):
    """A camera box sits in a corner of the picture; a game character does not."""
    x, y, w, h = box
    centre_x = (x + w / 2) / width
    centre_y = (y + h / 2) / height
    near_x = centre_x <= CORNER_EDGE or centre_x >= 1 - CORNER_EDGE
    near_y = centre_y <= CORNER_EDGE or centre_y >= 1 - CORNER_EDGE
    return near_x and near_y


def _face_tracks(frames, width, height):
    """Cluster the detections of every sampled frame into tracks of one face.

    A track is only worth anything when the same face shows up in at least two
    frames: a single detection in a game frame is a rendered character.
    """
    tracks = []
    for index, (_, boxes) in enumerate(frames):
        for box in boxes:
            for track in tracks:
                if _same_face(track['first'], box, width, height):
                    track['frames'].add(index)
                    track['boxes'].append(box)
                    break
            else:
                tracks.append({'first': box, 'frames': {index}, 'boxes': [box]})
    return [track for track in tracks if len(track['frames']) >= 2]


def detect(source, start_ms=0, duration_ms=None, *, samples=3):
    """Choose the pattern for a piece of footage and the regions it needs.

    A face that survives in the same place across the sampled frames is the
    only accepted evidence: a single detection in a game frame is a rendered
    character, not a camera.
    """
    from .framing import face_boxes, frame
    frames = []
    for index in range(samples):
        offset = start_ms + (duration_ms * (index + 1) / (samples + 1) if duration_ms else 0)
        try:
            image = frame(source, offset, width=DETECTION_WIDTH)
        except (OSError, ValueError):
            continue
        frames.append((image, face_boxes(image, min_size=20)))
    if not frames:
        return Pattern(SCREEN, Region(x=0, y=0, w=1, h=1), None,
                       'Кадры не получены: оставлен полный экран')
    height, width = frames[0][0].shape[:2]
    tracks = [{'box': _median_box(track['boxes']), 'frames': track['frames']}
              for track in _face_tracks(frames, width, height)]
    if not tracks:
        return Pattern(SCREEN, Region(x=0, y=0, w=1, h=1), None,
                       'Стабильного лица не найдено: оставлен полный экран')
    # A camera that fills the picture shows a face as wide as a sixth of the frame.
    big = [track for track in tracks if track['box'][2] / width >= CAMERA_WIDTH]
    if big:
        chosen = max(big, key=lambda track: track['box'][2] * track['box'][3])
        x, y, w, h = chosen['box']
        # The camera fills the picture: one vertical crop around the face.
        return Pattern(FACE, _vertical_camera(x + w / 2, width, height), None,
                       'Камера занимает кадр: только вебка')
    # A camera box sits in a corner of the picture; a game character does not.
    corners = [track for track in tracks if _in_corner(track['box'], width, height)]
    if not corners:
        # A face in the middle of a game screen is a rendered character.
        return Pattern(SCREEN, Region(x=0, y=0, w=1, h=1), None,
                       'В кадре нет вебки: оставлен полный экран')
    chosen = max(corners, key=lambda track: track['box'][2] * track['box'][3])
    x, y, w, h = chosen['box']
    camera = _camera_box(x, y, w, h, width, height)
    screen = _screen_box(camera)
    if screen.w * screen.h < MIN_SCREEN:
        return Pattern(SCREEN, Region(x=0, y=0, w=1, h=1), None,
                       'Отдельного экрана рядом с вебкой нет: оставлен полный кадр')
    return Pattern(SPLIT, camera, screen,
                   'Экран важен: вебка сверху, содержимое снизу')


def apply_pattern(segment, pattern):
    """Write the pattern into a segment as plain framing geometry."""
    note = ('Паттерн: ' + pattern.label + '. ' + segment.framing_note)[:500]
    if pattern.kind == SPLIT:
        return segment.model_copy(update={'framing': 'split', 'region': pattern.region,
                                          'secondary_region': pattern.secondary,
                                          'framing_note': note})
    if pattern.kind == FACE:
        return segment.model_copy(update={'framing': 'crop', 'region': pattern.region,
                                          'secondary_region': None, 'framing_note': note})
    return segment.model_copy(update={'framing': 'crop',
                                      'region': pattern.region or Region(x=0, y=0, w=1, h=1),
                                      'secondary_region': None, 'framing_note': note})


def resolve(plan, source):
    """Give every automatic segment a pattern that matches the footage.

    Segments whose geometry was chosen by hand keep it; only automatic ones
    are re-decided, because a split around a full-screen camera is the artefact
    the patterns exist to prevent.
    """
    cuts = []
    for segment in plan.segments:
        if segment.framing in ('split', 'crop') and not segment.framing_note.startswith('Авто'):
            cuts.append(segment)
            continue
        pattern = detect(source, segment.start_ms, segment.end_ms - segment.start_ms)
        cuts.append(apply_pattern(segment, pattern))
    return plan.model_copy(update={'segments': cuts})
