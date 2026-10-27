"""Request and response models of the public API (/api/v1). They define the OpenAPI schema the web client is typed from."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Engine = str  # an id from GET /api/v1/engines


class Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Ok(Model):
    ok: bool = True


# ---- session ---------------------------------------------------------------------------------------

class SessionCreate(BaseModel):
    key: str = Field(description="Access key")


class Session(Model):
    signed_in: bool


# ---- system ----------------------------------------------------------------------------------------

class GpuProcess(Model):
    pid: int
    memory: int
    own: bool
    label: str


class Gpu(Model):
    available: bool
    name: Optional[str] = None
    utilization: Optional[int] = None
    memory_used: Optional[int] = None
    memory_total: Optional[int] = None
    foreign_busy: Optional[bool] = None
    processes: list[GpuProcess] = []


class Status(Model):
    gpu: Gpu
    disk_free_gb: float
    elevenlabs: bool
    clone: bool
    engines: dict[str, bool]
    queue: dict
    training: int
    poll_minutes: int


# ---- engines and avatars ---------------------------------------------------------------------------

class EngineInfo(Model):
    id: str
    name: str = Field(description="Picker title, e.g. Realistic")
    model: str = Field(description="The model behind the engine, e.g. LatentSync 1.6")
    summary: str
    badge: Optional[str] = None
    needs: Literal["clip", "photo", "trained"] = Field(description="What an avatar must provide")
    backgrounds: bool = Field(description="Can replace the background")
    speech_models: bool = Field(description="Offers the avatar's speech-feature variants")
    background_note: str = ""
    speed: str
    licence: str
    available: bool = Field(description="Installed on this server")


class Variant(Model):
    feature: str
    label: str
    note: str
    metrics: dict = {}
    preview_url: Optional[str] = None
    poster_url: Optional[str] = None


class Avatar(Model):
    id: str
    name: str
    edition: Optional[str] = ""
    summary: Optional[str] = ""
    experiment: Optional[str] = None
    default_feature: str
    source: Literal["experiment", "studio", "quick"]
    engines: list[Engine]
    variants: list[Variant]


class QuickCreate(BaseModel):
    name: str = "Quick avatar"
    upload: str
    consent: bool


class Quick(Model):
    id: str
    name: str
    state: Literal["preparing", "ready", "failed"]
    detail: Optional[str] = None
    created: str
    seconds: Optional[float] = None


# ---- voices ----------------------------------------------------------------------------------------

class Voice(Model):
    id: str
    name: str
    gender: Optional[str] = ""
    accent: Optional[str] = ""
    style: Optional[str] = ""
    state: Optional[Literal["preparing", "ready", "failed"]] = None
    detail: Optional[str] = None
    sample_url: Optional[str] = None


class VoiceCatalogue(Model):
    elevenlabs: list[Voice]
    mms: list[Voice]
    clone: list[Voice]
    clone_available: bool


class VoiceSampleRequest(BaseModel):
    provider: Literal["elevenlabs", "mms"]
    id: str


class Url(Model):
    url: str


class CloneCreate(BaseModel):
    name: str = "My voice"
    upload: str
    consent: bool
    clip: Optional[str] = None
    text: Optional[str] = None


# ---- uploads ---------------------------------------------------------------------------------------

class UploadStart(BaseModel):
    kind: Literal["video", "audio", "background"]
    name: str = "file"
    size: int


class UploadTicket(Model):
    id: str
    chunk_limit: int


class UploadProgress(Model):
    received: int


class Upload(Model):
    id: str
    kind: str
    name: str
    size: int
    sha256: Optional[str] = None
    seconds: Optional[float] = None
    created: str


class Background(Model):
    id: str
    name: str
    url: str


# ---- renders ---------------------------------------------------------------------------------------

class VoiceChoice(BaseModel):
    provider: Literal["elevenlabs", "mms", "clone", "upload"]
    id: Optional[str] = None


class BackgroundChoice(BaseModel):
    type: Literal["original", "color", "image"] = "original"
    value: Optional[str] = None
    upload: Optional[str] = None


class RenderCreate(BaseModel):
    avatar: str
    feature: Optional[str] = Field(None, description="Speech model, for engines with speech_models")
    engine: Engine = "latentsync"
    text: str = ""
    voice: VoiceChoice
    audio_upload: Optional[str] = None
    background: BackgroundChoice = BackgroundChoice()
    title: Optional[str] = None


class Render(Model):
    id: str
    created: str
    updated: str
    state: Literal["queued", "voicing", "features", "waiting_gpu", "rendering", "encoding", "done", "failed", "cancelled"]
    detail: str = ""
    title: str
    text: str = ""
    avatar: str
    avatar_name: str
    feature: str
    engine: Engine = "gaussiantalker"
    engine_name: Optional[str] = None
    engine_model: Optional[str] = None
    voice: dict
    duration: Optional[float] = None
    published: Optional[str] = None
    video_url: Optional[str] = None
    poster_url: Optional[str] = None
    watch_url: Optional[str] = None


class PublishRequest(BaseModel):
    title: Optional[str] = None


# ---- training --------------------------------------------------------------------------------------

class TrainingCreate(BaseModel):
    name: str = "My avatar"
    uploads: list[str]
    consent: bool


class Crop(BaseModel):
    x: int
    y: int
    size: int


class TrainingApprove(BaseModel):
    crops: list[Crop]
    features: list[str]


class Training(Model):
    id: str
    name: str
    state: Literal["framing", "review", "training", "ready", "failed"]
    created: str
    features: list[str] = []
    crops: Optional[list[dict]] = None
    events: list[list[str]] = []
    progress: dict = {}
    ready_features: list[str] = []
    failure: Optional[str] = None
    active: bool = False
