# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""The incoming rate limit must pass real microphone audio at any frame size, and stop floods."""

from agent import main


def audio_message(ms: int) -> int:
    """Size in bytes of one binary frame carrying `ms` of 16 kHz 16-bit mono audio."""
    return 16 * 2 * ms


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def budgets(clock):
    return (main.TokenBucket(main.RATE_LIMIT_BYTES_PER_SECOND, main.RATE_LIMIT_BURST_BYTES, clock),
            main.TokenBucket(main.RATE_LIMIT_MESSAGES_PER_SECOND, main.RATE_LIMIT_BURST_MESSAGES, clock))


def stream(frame_ms: int, seconds: float, speed: float = 1.0) -> tuple[int, int]:
    """Send `seconds` of audio in `frame_ms` frames, `speed` times faster than real time.

    Returns (frames accepted, frames sent).
    """
    clock = FakeClock()
    by_bytes, by_count = budgets(clock)
    size, sent, accepted = audio_message(frame_ms), int(seconds * 1000 / frame_ms), 0
    for _ in range(sent):
        accepted += by_count.take(1) and by_bytes.take(size)
        clock.now += frame_ms / 1000 / speed
    return accepted, sent


def test_40ms_frames_all_pass():
    """25 messages a second: the old limit (50 per 10 s) dropped four in five of these."""
    accepted, sent = stream(40, seconds=60)
    assert accepted == sent


def test_256ms_frames_from_an_older_browser_still_pass():
    accepted, sent = stream(256, seconds=60)
    assert accepted == sent


def test_a_stalled_connection_can_flush_its_backlog():
    """A browser that couldn't send for a couple of seconds sends the queued frames at once."""
    clock = FakeClock()
    by_bytes, by_count = budgets(clock)
    size = audio_message(40)
    clock.now = 10.0  # idle, so the buckets are full
    backlog = [by_count.take(1) and by_bytes.take(size) for _ in range(50)]  # 2 s of audio
    assert all(backlog)


def test_sending_faster_than_real_time_is_cut_back_to_about_twice_real_time():
    speed, seconds = 4, 60
    accepted, sent = stream(40, seconds=seconds, speed=speed)
    elapsed = seconds / speed
    accepted_audio = accepted * 0.040
    burst_audio = main.RATE_LIMIT_BURST_BYTES / audio_message(40) * 0.040
    assert accepted < sent
    assert accepted_audio <= 2.1 * elapsed + burst_audio


def test_a_flood_of_tiny_messages_is_cut_off():
    clock = FakeClock()
    by_bytes, by_count = budgets(clock)
    accepted = 0
    for _ in range(10_000):  # 10,000 tiny messages in one second
        accepted += by_count.take(1) and by_bytes.take(20)
        clock.now += 0.0001
    assert accepted <= main.RATE_LIMIT_BURST_MESSAGES + main.RATE_LIMIT_MESSAGES_PER_SECOND
