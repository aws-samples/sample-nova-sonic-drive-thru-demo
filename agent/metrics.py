# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CloudWatch metrics, written as Embedded Metric Format (EMF) lines on stdout.

AgentCore Runtime sends the container's output to CloudWatch Logs, which turns each EMF line
into metric data points, so the agent needs no CloudWatch permissions or SDK calls for this.
The metrics carry no conversation content: only timings, counts and the reason a session ended.
"""

import json
import sys
import time

NAMESPACE = "DriveThru/VoiceAgent"
SERVICE = "DriveThruVoiceAgent"

# Metric names, with their CloudWatch units
RESPONSE_LATENCY = ("ResponseLatency", "Milliseconds")  # customer stops talking -> agent's first audio
CONNECTION_DURATION = ("ConnectionDuration", "Seconds")
# With a Reason dimension: why the session ended (order-complete, idle-timeout, ...), or
# "disconnected" / "replaced" for a connection whose session can still resume
CONNECTIONS_ENDED = ("ConnectionsEnded", "Count")
MODEL_RESTARTS = ("ModelRestarts", "Count")
DROPPED_FRAMES = ("DroppedFrames", "Count")  # browser frames rejected by size, rate or format


def emit(values: dict[tuple[str, str], float], **dimensions: str) -> None:
    """Write one EMF line with these metric values, under the Service dimension plus any others."""
    dims = {"Service": SERVICE, **dimensions}
    line = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [{
                "Namespace": NAMESPACE,
                "Dimensions": [sorted(dims)],
                "Metrics": [{"Name": name, "Unit": unit} for name, unit in values],
            }],
        },
        **dims,
        **{name: value for (name, _), value in values.items()},
    }
    sys.stdout.write(json.dumps(line) + "\n")
    sys.stdout.flush()


class ResponseTimer:
    """Times each reply: from the customer's finished utterance to the agent's first audio."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._heard_at: float | None = None

    def customer_finished(self) -> None:
        self._heard_at = self._clock()

    def interrupted(self) -> None:
        self._heard_at = None  # the reply was cut off; the next utterance starts a new timing

    def agent_spoke(self) -> float | None:
        """Milliseconds since the customer finished, for the first audio of a reply; else None."""
        if self._heard_at is None:
            return None
        elapsed = (self._clock() - self._heard_at) * 1000
        self._heard_at = None
        return elapsed
