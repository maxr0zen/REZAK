"""Montage styles for short-form clips, derived from inspected reference clips.

Every number below was measured on the reference frame itself, not guessed:
the panel boundary, the caption box, the glyph width of a known word and the
size of the small webcam replay. Styles are data so the FFmpeg renderer and
the FilmCraft renderer describe the same picture.
"""
from dataclasses import dataclass
from pathlib import Path

FONT_DIR = Path(__file__).with_name('fonts')


@dataclass(frozen=True)
class CaptionStyle:
    family: str
    style: str
    size: int
    color: str
    outline_color: str
    outline: int
    shadow: int
    uppercase: bool
    scale_x: int = 100
    # FilmCraft draws the captions itself: it needs its own size in pixels and
    # the stroke width in pixels. 55.5 px with the bundled wide face reproduces
    # the reference ink box (211x53 px in a 1080x1920 frame).
    fc_size: float = 55.5
    fc_stroke: int = 6


@dataclass(frozen=True)
class PanelStyle:
    """Face panel on top, gameplay below, both cropped from one source frame."""
    face_ratio: float
    gap_ratio: float
    replay: tuple | None
    caption_center: float | None = None


@dataclass(frozen=True)
class TikTokStyle:
    key: str
    title: str
    reference: str
    notes: str
    caption: CaptionStyle
    panel: PanelStyle
    # Without a split there is no panel boundary to sit on, so the caption
    # moves to the lower third of a single camera crop.
    caption_center_face: float = 0.72

    def caption_center(self, pattern='split'):
        """Vertical centre of the caption band, as a share of the height."""
        if pattern != 'split':
            return self.caption_center_face
        if self.panel.caption_center is None:
            return self.panel.face_ratio + self.panel.gap_ratio / 2
        return self.panel.caption_center

    def caption_baseline(self, height, pattern='split'):
        """Vertical centre of the caption band, in output pixels."""
        return round(height * self.caption_center(pattern))

    def panel_heights(self, height):
        face = round(height * self.panel.face_ratio) // 2 * 2
        gap = round(height * self.panel.gap_ratio) // 2 * 2
        return face, gap, height - face - gap


# Reference: https://www.youtube.com/shorts/uUJLJcp1JWs (channel @narezkaa_t2x2).
# Measured on a 608x1080 frame: panel boundary at y=456 (0.422 of the height),
# the caption word "ребат" spanning 119 px (0.196 of the width) with a 30 px ink
# height, white fill with a black outline, centred just above the boundary, and
# a 49x169 webcam replay in the lower right corner of the gameplay panel.
# Montserrat ExtraBold at 89 px with a 119% horizontal scale reproduces both the
# width and the height of the reference glyphs: the reference face is about 19%
# wider than Montserrat ExtraBold for the same letter height.
# libass renders this face at 0.62 of the nominal size (its own vertical metrics
# drive the scale), so the numbers above are script units, not output pixels.
# FilmCraft draws the same face through its own text engine, which needs the
# size in pixels (55.5) and cannot stretch a face, so the studio ships the
# stretched "Rezak Wide" face (Montserrat ExtraBold stretched by 1.225) for it.
T2X2 = TikTokStyle(
    key='t2x2',
    title='Сплит лицо/игра',
    reference='https://www.youtube.com/shorts/uUJLJcp1JWs',
    notes=('Горизонтальный сплит: вебка сверху, геймплей снизу. Подпись — одно слово '
           'за раз, жирный геометрический шрифт, белая заливка с чёрной обводкой, '
           'по центру над линией разбивки. В правом нижнем углу геймплея — маленькое '
           'повторение вебки. Свои логотипы и чужие реплики не копировать.'),
    caption=CaptionStyle(
        family='Rezak Caption',
        style='ExtraBold',
        size=89,
        color='&H00FFFFFF&',
        outline_color='&H00000000&',
        outline=9,
        shadow=0,
        uppercase=False,
        scale_x=119,
    ),
    panel=PanelStyle(
        face_ratio=0.4222,
        gap_ratio=0.0,
        replay=(0.919, 0.778, 0.079, 0.156),
        caption_center=0.4199,
    ),
)

# The studio default: yellow words on a black outline over the whole frame.
DEFAULT = TikTokStyle(
    key='default',
    title='Студийный',
    reference='',
    notes='Жёлтые подписи с чёрной обводкой во всю высоту кадра.',
    caption=CaptionStyle(
        family='DejaVu Sans',
        style='Bold',
        size=104,
        color='&H0000E8FF&',
        outline_color='&H00000000&',
        outline=10,
        shadow=2,
        uppercase=True,
    ),
    panel=PanelStyle(face_ratio=0.35, gap_ratio=0.0625, replay=None),
)

STYLES = {style.key: style for style in (DEFAULT, T2X2)}


def get_style(key):
    return STYLES.get(key or 'default', DEFAULT)


def caption_font_path():
    """Bundled caption face, so a clean machine renders the same glyphs."""
    return FONT_DIR / 'RezakCaption-ExtraBold.ttf'
