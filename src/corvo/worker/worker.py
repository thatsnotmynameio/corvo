from hatchet_sdk import Worker

from corvo.worker.hatchet_client import hatchet
from corvo.worker.tasks.hello import hello


def create_worker() -> Worker:
    return hatchet.worker("corvo-worker", workflows=[hello])


def main() -> None:
    create_worker().start()
