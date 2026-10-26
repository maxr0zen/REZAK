from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class Interval(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must exceed start_ms")
        return self

class Caption(Interval):
    text: str = Field(min_length=1, max_length=160)
    kind: Literal['speech','word','emphasis'] = 'speech'
    reason: str = Field(default='',max_length=700)

    @model_validator(mode="after")
    def plain_text(self):
        if any(c in self.text for c in "{}\\") or any(ord(c) < 32 and c != "\n" for c in self.text):
            raise ValueError("subtitle markup/control characters are forbidden")
        if self.kind=='emphasis' and len(self.reason.strip())<20:
            raise ValueError('Exceptional caption requires a concrete justification')
        return self

class Region(StrictModel):
    x: float = Field(ge=0,le=1)
    y: float = Field(ge=0,le=1)
    w: float = Field(gt=0,le=1)
    h: float = Field(gt=0,le=1)

    @model_validator(mode='after')
    def bounds(self):
        if self.x+self.w>1.000001 or self.y+self.h>1.000001:raise ValueError('Область выходит за границы кадра')
        if self.w<.03 or self.h<.03:raise ValueError('Область слишком мала')
        return self

class Segment(Interval):
    template: Literal["fit_pad"] = "fit_pad"
    evidence_refs: list[str] = Field(default_factory=list)
    framing: Literal['fit','crop','split'] = 'fit'
    region: Region | None = None
    secondary_region: Region | None = None
    framing_note: str = Field(default='',max_length=500)
    preserve_pauses: bool=False

    @model_validator(mode='after')
    def framing_regions(self):
        if self.framing in ('crop','split') and self.region is None:raise ValueError('Укажите область кадрирования')
        if self.framing=='split' and self.secondary_region is None:raise ValueError('Укажите вторую область')
        return self

class EditPlan(StrictModel):
    schema_version: Literal[1]
    source_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    profile: Literal["vertical", "horizontal"]
    title: str = Field(default='',max_length=240)
    hook_title: str = Field(default='',max_length=84)

    @model_validator(mode='after')
    def safe_hook_title(self):
        if any(c in self.hook_title for c in '{}\\\r\n') or any(ord(c)<32 for c in self.hook_title):raise ValueError('Headline must be plain single-line text')
        return self
    segments: list[Segment] = Field(min_length=1, max_length=1000)
    captions: list[Caption] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def no_overlap(self):
        ordered = sorted(self.segments, key=lambda s: s.start_ms)
        if any(a.end_ms > b.start_ms for a, b in zip(ordered, ordered[1:])):
            raise ValueError("source intervals overlap or repeat")
        duration = sum(s.end_ms-s.start_ms for s in self.segments)
        if duration > (180000 if self.profile == "vertical" else 14400000):
            raise ValueError("profile duration exceeded")
        return self

    def validate_media(self, duration_ms: int, gaps: list[Interval]):
        for segment in self.segments:
            if segment.end_ms > duration_ms:
                raise ValueError("segment exceeds source duration")
            if any(segment.start_ms < gap.end_ms and segment.end_ms > gap.start_ms for gap in gaps):
                raise ValueError("segment intersects a recording gap")
        if any(c.end_ms > duration_ms for c in self.captions):
            raise ValueError("caption exceeds source duration")

    def timeline_captions(self):
        offset = 0
        for segment in self.segments:
            for caption in self.captions:
                start, end = max(segment.start_ms, caption.start_ms), min(segment.end_ms, caption.end_ms)
                if start < end:
                    yield caption.model_copy(update={'start_ms':offset+start-segment.start_ms,'end_ms':offset+end-segment.start_ms})
            offset += segment.end_ms-segment.start_ms
