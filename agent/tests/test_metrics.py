# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CloudWatch metrics: the EMF lines are valid, and the handler reports what happened."""

import json

from agent import metrics


def emf_lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{"_aws"')]


def test_an_emf_line_declares_its_metrics_and_dimensions(capsys):
    metrics.emit({metrics.CONNECTIONS_ENDED: 1}, Reason="order-complete")
    [line] = emf_lines(capsys)
    [directive] = line["_aws"]["CloudWatchMetrics"]
    assert directive["Namespace"] == metrics.NAMESPACE
    assert directive["Dimensions"] == [["Reason", "Service"]]
    assert directive["Metrics"] == [{"Name": "ConnectionsEnded", "Unit": "Count"}]
    assert line["ConnectionsEnded"] == 1 and line["Reason"] == "order-complete"
    assert line["Service"] == metrics.SERVICE


def test_response_latency_is_timed_from_the_customer_to_the_first_audio_of_the_reply():
    now = [0.0]
    timer = metrics.ResponseTimer(clock=lambda: now[0])
    assert timer.agent_spoke() is None  # the greeting: nobody spoke first
    timer.customer_finished()
    now[0] = 0.8
    assert timer.agent_spoke() == 800
    now[0] = 0.9
    assert timer.agent_spoke() is None  # later audio of the same reply
    timer.customer_finished()
    timer.interrupted()
    assert timer.agent_spoke() is None
