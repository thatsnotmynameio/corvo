"""The framing of what crosses an agent container's standard streams.

A frame is its payload's length in ASCII decimal, a newline, then exactly
that many bytes, at most MAX_UNTRUSTED_BYTES. The header is digits alone,
with no sign, space or leading zero, and a length of zero is invalid. Only
the first frame counts, and it must start at the first byte; bytes after
it are ignored. The worker writes the request this way to the container's
stdin, and the runner its envelope or probe report to its stdout, so
neither side waits for the end of its input. The worker imports this
module, so it uses the standard library alone.
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


def digits(header: bytes | bytearray) -> bool:
    """Whether the bytes could begin a valid header: digits, the first not 0."""
    return header.isdigit() and not header.startswith(b"0")


def header(data: bytes | bytearray) -> tuple[int, int] | None:
    """Where the payload of the frame at the start of <data> begins, and its
    length, or None while the header is not all there."""
    newline = data.find(b"\n", 0, MAX_HEADER)
    if newline < 0:
        if len(data) >= MAX_HEADER or (data and not digits(data)):
            raise FrameError("an invalid frame header")
        return None
    if not digits(data[:newline]):
        raise FrameError("an invalid frame header")
    size = int(data[:newline])
    if size > MAX_UNTRUSTED_BYTES:
        raise FrameError(f"a frame of {size} bytes, over {MAX_UNTRUSTED_BYTES}")
    return newline + 1, size


def extract(data: bytes | bytearray) -> bytes | None:
    """The payload of the frame at the start of <data>, or None while it is
    not all there."""
    parsed = header(data)
    if parsed is None:
        return None
    start, size = parsed
    if len(data) - start < size:
        return None
    return bytes(data[start : start + size])


def read_frame(fd: int, timeout: float) -> bytes:
    """The payload of the first frame on <fd>, read within <timeout> seconds
    in all. It reads less than a header's length past the frame's end."""
    deadline = time.monotonic() + timeout
    data = bytearray()
    while (payload := extract(data)) is None:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise FrameError(f"the deadline, after {len(data)} bytes")
        parsed = header(data)
        end = MAX_HEADER if parsed is None else sum(parsed)
        chunk = os.read(fd, min(end - len(data), CHUNK))
        if not chunk:
            raise FrameError(f"a frame truncated after {len(data)} bytes")
        data += chunk
    return payload
