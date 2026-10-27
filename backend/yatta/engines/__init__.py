"""Video engines, one module each. The studio, the API and the web app read this registry and nothing else.

To add a model: write ``yatta/engines/<name>.py`` with an ``Engine`` subclass (see ``base.py``) and list it in
ENGINES. Its ``available()`` check hides it until the model is installed on the server.
"""

from yatta.engines.base import Engine, RenderJob, face_clip, face_photo  # noqa: F401
from yatta.engines.gaussiantalker import GaussianTalker
from yatta.engines.latentsync import LatentSync
from yatta.engines.longcat import LongCat

ENGINES = {engine.id: engine for engine in (LatentSync(), LongCat(), GaussianTalker())}  # picker order


def get(engine_id):
    """The engine with this id, or KeyError."""
    return ENGINES[engine_id]


def info():
    return [engine.info() for engine in ENGINES.values()]


def for_avatar(avatar):
    """Ids of the installed engines that can render this avatar."""
    return [engine.id for engine in ENGINES.values() if engine.available() and engine.supports(avatar)]
