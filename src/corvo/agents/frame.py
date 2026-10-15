"""The framing of what crosses an agent container's standard streams.

A frame is its payload's length in ASCII decimal, a newline, then exactly
that many bytes, at most MAX_UNTRUSTED_BYTES. The header is digits alone,
with no sign, space or leading zero, and a length of zero is invalid. Only
the first frame counts; bytes after it are ignored. The worker writes the
request this way to the container's stdin, and the runner reads it so,
without waiting for the end of its input. The worker imports this module,
so it uses the standard library alone.
"""

import os
import select
import time

# Every byte read from the container is untrusted, and capped.
MAX_UNTRUSTED_BYTES = 1024 * 1024

# The longest header of a valid frame: the cap's digits and the newline.
MAX_HEADER = len(str(MAX_UNTRUSTED_BYTES)) + 1

# The most read from the descriptor at once.
CHUNK = 64 * 1024


class FrameError(ValueError):
    """A frame that is malformed, too large or truncated, or that did not
    arrive in time. Its message names sizes at most, never content."""


def encode(payload: bytes) -> bytes:
    if not 0 < len(payload) <= MAX_UNTRUSTED_BYTES:
        raise FrameError(
            f"a payload of {len(payload)} bytes, outside 1 to {MAX_UNTRUSTED_BYTES}"
        )
    return b"%d\n" % len(payload) + payload


def length(header: bytes) -> int:
    """The payload's length a header without its newline gives."""
    if not header.isdigit() or header.startswith(b"0"):
        raise FrameError("an invalid frame header")
    size = int(header)
    if size > MAX_UNTRUSTED_BYTES:
        raise FrameError(f"a frame of {size} bytes, over {MAX_UNTRUSTED_BYTES}")
    return size


def read_frame(fd: int, timeout: float) -> bytes:
    """The payload of the first frame on <fd>, read within <timeout> seconds
    in all. It reads at most MAX_HEADER bytes past the frame's end."""
    deadline = time.monotonic() + timeout
    data = bytearray()
    size: int | None = None
    while True:
        if size is None:
            newline = data.find(b"\n")
            if newline >= 0:
                size = length(bytes(data[:newline]))
                del data[: newline + 1]
            elif len(data) >= MAX_HEADER:
                raise FrameError("an invalid frame header")
        if size is not None and len(data) >= size:
            return bytes(data[:size])
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise FrameError(f"the deadline, {len(data)} bytes into a frame")
        wanted = MAX_HEADER - len(data) if size is None else size - len(data)
        chunk = os.read(fd, min(wanted, CHUNK))
        if not chunk:
            raise FrameError(f"a frame truncated after {len(data)} bytes")
        data += chunk
