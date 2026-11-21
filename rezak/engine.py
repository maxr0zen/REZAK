"""Chooses the montage engine and the montage style for a plan.

The studio can assemble a short video with the bundled FFmpeg pipeline or with
the FilmCraft engine over MCP. The reference split style ("t2x2") needs both
engines to agree on the picture, so the style lives in one place
(rezak.tiktok) and is applied here before the render starts.
"""
from pathlib import Path

from .tiktok import STYLES, get_style

ENGINES = ('ffmpeg', 'filmcraft')
STYLES_KEYS = tuple(STYLES)


def engine_name(store):
    """The engine the studio is configured to use."""
    if store is None:
        return 'ffmpeg'
    name = str(store.setting('render_engine', 'ffmpeg') or 'ffmpeg').lower()
    return name if name in ENGINES else 'ffmpeg'


def style_name(store):
    """The montage style the studio is configured to use."""
    if store is None:
        return style_from_environment()
    name = str(store.setting('montage_style', 'default') or 'default').lower()
    return name if name in STYLES_KEYS else 'default'


def style_from_environment(default='default'):
    """The style requested by the studio for the container pipeline."""
    import os
    name = str(os.environ.get('REZAK_MONTAGE_STYLE', '') or default).lower()
    return name if name in STYLES_KEYS else default


def apply_style(plan, style_key):
    """Mark the plan as the requested style.

    The geometry is not touched here: whether the picture is a split or a
    single camera crop depends on the footage, and that decision belongs to
    the pattern detector (rezak.patterns), not to the style name.
    """
    style = get_style(style_key)
    if style.key == 'default' or plan.profile != 'vertical':
        return plan
    return plan.model_copy(update={'style': style.key})


def style_plan(plan, style_key, source):
    """Apply the style and pick a pattern for every automatic segment."""
    plan = apply_style(plan, style_key)
    if plan.style == 'default':
        return plan
    from .patterns import resolve
    return resolve(plan, source)


def render_plan(plan, root, *, store=None, cancel=None, progress_base=0, progress_scale=1):
    """Render a plan with the engine the studio is configured to use."""
    from .media import source_path
    style_key = style_name(store)
    if style_key != 'default':
        plan = style_plan(plan, style_key, source_path(Path(root), plan.source_id))
    if engine_name(store) == 'filmcraft':
        from .filmcraft import EngineError, available
        from .filmcraft import render as filmcraft_render
        if plan.style != 'default' and available(store):
            def progress(value, message):
                from .events import emit
                emit('render', progress_base + progress_scale * value, message)
            return filmcraft_render(plan, root, store=store, progress=progress, cancel=cancel)
    from .render import render
    return render(plan, root, cancel=cancel, progress_base=progress_base, progress_scale=progress_scale)
