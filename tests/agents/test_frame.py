import os
import threading
import time
from collections.abc import Iterator

import pytest

from corvo.agents.frame import (
    MAX_UNTRUSTED_BYTES,
    FrameError,
    encode,
    extract,
    read_frame,
)


@pytest.fixture
def pipe() -> Iterator[tuple[int, int]]:
    read_end, write_end = os.pipe()
    yield read_end, write_end
    os.close(read_end)
    try:
        os.close(write_end)
    except OSError:
        pass


def fed(pipe: tuple[int, int], data: bytes, *, close: bool = True) -> int:
    """The pipe's read end, once <data> sits in it."""
    read_end, write_end = pipe
    os.write(write_end, data)
    if close:
        os.close(write_end)
    return read_end


def test_a_payload_round_trips(pipe: tuple[int, int]) -> None:
    payload = b'{"agent": "tone"}'

    assert encode(payload) == b"17\n" + payload
    assert read_frame(fed(pipe, encode(payload)), timeout=1) == payload


def test_a_payload_of_the_cap_round_trips() -> None:
    payload = b"x" * MAX_UNTRUSTED_BYTES
    read_end, write_end = os.pipe()
    writer = threading.Thread(target=lambda: os.write(write_end, encode(payload)))
    writer.start()
    try:
        assert read_frame(read_end, timeout=10) == payload
    finally:
        writer.join()
        os.close(read_end)
        os.close(write_end)


@pytest.mark.parametrize("size", [0, MAX_UNTRUSTED_BYTES + 1])
def test_a_payload_outside_the_bounds_is_refused(size: int) -> None:
    with pytest.raises(FrameError, match=f"a payload of {size} bytes"):
        encode(b"x" * size)


@pytest.mark.parametrize(
    "header",
    [b"+5", b"-5", b" 5", b"5 ", b"05", b"5a", b"0", b"", b"\xd9\xa5"],
)
def test_an_invalid_header_is_refused(pipe: tuple[int, int], header: bytes) -> None:
    with pytest.raises(FrameError, match="invalid frame header"):
        read_frame(fed(pipe, header + b"\nhello"), timeout=1)


def test_a_header_over_the_cap_is_refused(pipe: tuple[int, int]) -> None:
    header = b"%d\n" % (MAX_UNTRUSTED_BYTES + 1)

    with pytest.raises(FrameError, match=f"over {MAX_UNTRUSTED_BYTES}"):
        read_frame(fed(pipe, header), timeout=1)


def test_a_header_with_no_newline_in_its_length_is_refused(
    pipe: tuple[int, int],
) -> None:
    with pytest.raises(FrameError, match="invalid frame header"):
        read_frame(fed(pipe, b"1" * 100, close=False), timeout=1)


def test_a_frame_cut_short_by_the_end_of_input_is_truncated(
    pipe: tuple[int, int],
) -> None:
    with pytest.raises(FrameError, match="truncated after 8 bytes"):
        read_frame(fed(pipe, b"10\nhello"), timeout=1)


def test_a_frame_whose_bytes_never_arrive_ends_at_the_deadline(
    pipe: tuple[int, int],
) -> None:
    with pytest.raises(FrameError, match="the deadline, after 8 bytes"):
        read_frame(fed(pipe, b"10\nhello", close=False), timeout=0.2)


def test_the_deadline_is_total_across_a_slow_trickle(pipe: tuple[int, int]) -> None:
    read_end, write_end = pipe
    stop = threading.Event()

    def trickle() -> None:
        for byte in b"100\n" + b"x" * 100:
            if stop.wait(0.05):
                return
            os.write(write_end, bytes([byte]))

    writer = threading.Thread(target=trickle)
    writer.start()
    started = time.monotonic()
    try:
        with pytest.raises(FrameError, match="deadline"):
            read_frame(read_end, timeout=0.5)
    finally:
        stop.set()
        writer.join()
    assert time.monotonic() - started < 1


def test_bytes_after_the_first_frame_are_ignored(pipe: tuple[int, int]) -> None:
    assert read_frame(fed(pipe, b"3\nabc7\nanother"), timeout=1) == b"abc"


def test_a_whole_frame_is_extracted_and_what_follows_ignored() -> None:
    assert extract(encode(b"abc") + b"7\nanother") == b"abc"


@pytest.mark.parametrize("data", [b"", b"1", b"12\n", b"12\nhello"])
def test_a_frame_not_all_there_is_missing(data: bytes) -> None:
    assert extract(data) is None


@pytest.mark.parametrize(
    "data", [b"garbage", b"05", b"-3\nabc", b"1" * 100, b" 3\nabc", b"x" + encode(b"a")]
)
def test_bytes_that_start_no_frame_are_invalid(data: bytes) -> None:
    with pytest.raises(FrameError, match="invalid frame header"):
        extract(data)


def test_a_frame_over_the_cap_is_invalid() -> None:
    with pytest.raises(FrameError, match=f"over {MAX_UNTRUSTED_BYTES}"):
        extract(b"%d\n" % (MAX_UNTRUSTED_BYTES + 1))
