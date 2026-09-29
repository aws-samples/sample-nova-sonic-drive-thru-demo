// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { VoiceSessionManager } from './VoiceSessionManager';
import type { AgentCoreWebSocketClient, BidiEvent } from './WebSocketClient';
import { useAppStore } from '../store/appStore';

/** A client whose server can be told to drop the connection or end the session. */
function fakeClient() {
  let onEvent: (e: BidiEvent) => void = () => {};
  let onDisconnect: () => void = () => {};
  const client = {
    connects: [] as string[],
    connect: vi.fn(async (_arn: string, _region: string, _token: string, sessionId: string) => {
      client.connects.push(sessionId);
    }),
    disconnect: vi.fn(),
    send: vi.fn(),
    onEvent: (cb: (e: BidiEvent) => void) => { onEvent = cb; },
    onDisconnect: (cb: () => void) => { onDisconnect = cb; },
    getState: () => 'connected' as const,
    serverSends: (e: BidiEvent) => onEvent(e),
    serverCloses: () => onDisconnect(),
  };
  return client;
}

class FakeAudioWorkletNode {
  static last: FakeAudioWorkletNode | null = null;
  port: { onmessage: ((e: { data: { pcm: ArrayBuffer; rms: number } }) => void) | null } = { onmessage: null };
  name: string;
  options: { processorOptions: { frameSize: number } };
  constructor(_context: unknown, name: string, options: { processorOptions: { frameSize: number } }) {
    this.name = name;
    this.options = options;
    FakeAudioWorkletNode.last = this;
  }
  /** What the worklet posts for each captured frame. */
  frame(rms: number) {
    this.port.onmessage?.({ data: { pcm: new Int16Array(640).buffer, rms } });
  }
}

class FakeAudioContext {
  state = 'running';
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => {}) };
  createMediaStreamSource() { return { connect: () => {} }; }
  createScriptProcessor() { return { connect: () => {}, onaudioprocess: null }; }
  createBuffer() { return { getChannelData: () => ({ set: () => {} }) }; }
  createBufferSource() { return { connect: () => {}, start: () => {}, stop: () => {}, onended: null }; }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}

async function started(client: ReturnType<typeof fakeClient>) {
  const onEnded = vi.fn();
  const manager = new VoiceSessionManager(client as unknown as AgentCoreWebSocketClient, onEnded);
  await manager.startSession('arn', 'us-east-1', async () => 'token');
  return { manager, onEnded };
}

/** The server accepts the reconnect and then fails straight away, as it did while Nova Sonic was erroring. */
async function failAfterEachReconnect(client: ReturnType<typeof fakeClient>, times: number) {
  for (let i = 0; i < times; i++) {
    client.serverCloses();
    await vi.runAllTimersAsync();
  }
}

describe('VoiceSessionManager reconnects', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('AudioContext', FakeAudioContext);
    vi.stubGlobal('AudioWorkletNode', FakeAudioWorkletNode);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [] }) } });
    useAppStore.getState().resetAgentUI();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('reconnects a dropped connection to the same session', async () => {
    const client = fakeClient();
    const { onEnded } = await started(client);
    await failAfterEachReconnect(client, 1);
    expect(client.connects).toHaveLength(2);
    expect(client.connects[1]).toBe(client.connects[0]);
    expect(onEnded).not.toHaveBeenCalled();
    expect(useAppStore.getState().voice.reconnecting).toBe(false);
  });

  it('gives up on a connection that keeps failing as soon as it opens', async () => {
    const client = fakeClient();
    const { onEnded } = await started(client);
    await failAfterEachReconnect(client, 10);
    expect(client.connects).toHaveLength(1 + 5); // the first connection, then 5 attempts in all
    expect(onEnded).toHaveBeenCalledOnce();
    expect(onEnded.mock.calls[0][1]).toBeNull();
  });

  it('gets a fresh set of attempts once the agent is heard again', async () => {
    const client = fakeClient();
    const { onEnded } = await started(client);
    for (let i = 0; i < 8; i++) {
      await failAfterEachReconnect(client, 1);
      client.serverSends({ type: 'bidi_audio_stream', audio: '', sample_rate: 16000 });
    }
    expect(client.connects).toHaveLength(1 + 8);
    expect(onEnded).not.toHaveBeenCalled();
  });

  it('captures the mic in 40 ms frames and sends each one as 16 kHz PCM', async () => {
    const client = fakeClient();
    await started(client);
    const node = FakeAudioWorkletNode.last!;
    expect(node.name).toBe('audio-capture');
    expect(node.options.processorOptions.frameSize).toBe(640); // 40 ms at 16 kHz
    node.frame(0.001);
    expect(client.send).toHaveBeenCalledOnce();
    const sent = client.send.mock.calls[0][0] as BidiEvent;
    expect(sent).toMatchObject({ type: 'bidi_audio_input', format: 'pcm', sample_rate: 16000, channels: 1 });
    expect(atob(sent.audio as string)).toHaveLength(1280); // 640 16-bit samples
  });

  it('while the agent talks, only sends frames loud enough to be the customer', async () => {
    const client = fakeClient();
    await started(client);
    client.serverSends({ type: 'bidi_audio_stream', audio: '', sample_rate: 16000 });
    FakeAudioWorkletNode.last!.frame(0.005); // its own voice coming back through the mic
    FakeAudioWorkletNode.last!.frame(0.2); // the customer interrupting
    expect(client.send).toHaveBeenCalledOnce();
  });

  it('does not reconnect when the agent reports an error', async () => {
    const client = fakeClient();
    const { onEnded } = await started(client);
    client.serverSends({ type: 'CUSTOM', name: 'session_ended', value: { reason: 'agent-error' } });
    await failAfterEachReconnect(client, 1);
    expect(client.connects).toHaveLength(1);
    expect(onEnded).toHaveBeenCalledWith(expect.stringContaining('ran into a problem'), 'agent-error');
  });
});
