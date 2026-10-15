from corvo.agents.envelope import ProbeReport
from corvo.agents.fingerprint import fingerprint
from corvo.worker.agent_runtime.spec import ISOLATION_ENV
from corvo.worker.defaults import AGENT_MEMORY, AGENT_PIDS_LIMIT


def matching_report(**changes: object) -> ProbeReport:
    """What the probe reads in a container built by the spec, from an image
    of this checkout, with changes made to it."""
    fields: dict[str, object] = {
        "fingerprint": fingerprint(),
        "memory_max": str(AGENT_MEMORY),
        "cpu_max": "100000 100000",
        "pids_max": str(AGENT_PIDS_LIMIT),
        "cap_eff": "0000000000000000",
        "env_names": sorted([*ISOLATION_ENV, "PATH"]),
        "root_read_only": True,
        "mounts": {
            "/tmp": ["rw", "nosuid", "nodev", "noexec", "relatime", "size=102400k"],
            "/home/agent": [
                "rw",
                "nosuid",
                "nodev",
                "noexec",
                "relatime",
                "size=512000k",
            ],
        },
        "gateway": "10.0.2.2",
        "gateway_reachable": False,
        "metadata_reachable": False,
    }
    return ProbeReport.model_validate(fields | changes)
