import dataclasses
import importlib
import logging
import signal
import sys
from collections.abc import Callable
from types import FrameType

from corvo.settings import get_settings
from corvo.worker.hatchet_client import hatchet
from corvo.worker.profiles import PROFILES, Profile

logger = logging.getLogger(__name__)


def serve(profile: Profile) -> None:
    if profile.before_start is not None:
        profile.before_start()
    worker = hatchet.worker(
        profile.name, slots=profile.slots, workflows=profile.workflows
    )
    if profile.on_sigterm is not None:
        # Hatchet's Worker installed its own handler; this one runs first.
        install_sigterm(profile.on_sigterm)
    worker.start()


def install_sigterm(hook: Callable[[], None]) -> None:
    hatchet_handler = signal.getsignal(signal.SIGTERM)

    def handle(signum: int, frame: FrameType | None) -> None:
        hook()
        if callable(hatchet_handler):
            hatchet_handler(signum, frame)

    signal.signal(signal.SIGTERM, handle)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    name = settings.worker_profile
    if name not in PROFILES:
        logger.error(
            "unknown worker profile %r: the profiles are %s",
            name,
            ", ".join(sorted(PROFILES)),
        )
        sys.exit(1)
    # By name, so the main profile never imports the agents profile's tasks.
    profile: Profile = importlib.import_module(PROFILES[name]).PROFILE
    # Blank keeps the profile's name: Hatchet's names hold no spaces.
    if worker_name := settings.worker_name.strip():
        profile = dataclasses.replace(profile, name=worker_name)
    serve(profile)
