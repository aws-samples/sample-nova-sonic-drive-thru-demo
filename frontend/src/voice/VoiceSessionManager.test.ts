// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { PLAYBACK_LEAD_SECONDS, VoiceSessionManager } from './VoiceSessionManager';
import type { AgentCoreWebSocketClient } from './WebSocketClient';
import type { ServerMessage } from '../protocol/messages';
import { useAppStore } from '../store/appStore';

/** 40 ms of the agent's voice, as one binary frame: 640 16-bit samples. */
const agentAudio = () => new Int16Array(640).fill(1000).buffer;

/** A client whose server can be told to talk, drop the connection or end the session. */
function fakeClient() {
  let onMessage: (m: ServerMessage) => void = () => {};
  let onAudio: (pcm: ArrayBuffer) => void = () => {};
  let onDisconnect: () => void = () => {};
  const client = {
    connects: [] as string[],
    connect: vi.fn(async (_arn: string, _region: string, _token: string, sessionId: string) => {
      client.connects.push(sessionId);
    }),
    disconnect: vi.fn(),
    sendAudio: vi.fn(),
    onMessage: (cb: (m: ServerMessage) => void) => { onMessage = cb; },
    onAudio: (cb: (pcm: ArrayBuffer) => void) => { onAudio = cb; },
    onDisconnect: (cb: () => void) => { onDisconnect = cb; },
    getState: () => 'connected' as const,
    serverSends: (m: ServerMessage) => onMessage(m),
    serverSpeaks: (pcm: ArrayBuffer = agentAudio()) => onAudio(pcm),
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

class FakeSource {
  buffer: { duration: number } | null = null;
  startedAt: number | null = null;
  stopped = false;
  onended: (() => void) | null = null;
  connect() {}
  start(when = 0) { this.startedAt = when; }
  stop() { this.stopped = true; }
}

class FakeAudioContext {
  static playback: FakeAudioContext[] = [];
  state = 'running';
  currentTime = 0;
  destination = {};
  sources: FakeSource[] = [];
  audioWorklet = { addModule: vi.fn(async () => {}) };
  constructor() { FakeAudioContext.playback.push(this); }
  createMediaStreamSource() { return { connect: () => {} }; }
  createBuffer(_channels: number, length: number, sampleRate: number) {
    return { duration: length / sampleRate, getChannelData: () => ({ set: () => {} }) };
  }
  createBufferSource() {
    const source = new FakeSource();
    this.sources.push(source);
    return source;
  }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}

/** The context the agent's voice plays on. */
const playback = () => FakeAudioContext.playback.find((c) => c.sources.length > 0)!;

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
    FakeAudioContext.playback = [];
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
      client.serverSpeaks();
    }
    expect(client.connects).toHaveLength(1 + 8);
    expect(onEnded).not.toHaveBeenCalled();
  });

  it('captures the mic in 40 ms frames and sends each one as a binary frame of 16-bit PCM', async () => {
    const client = fakeClient();
    await started(client);
    const node = FakeAudioWorkletNode.last!;
    expect(node.name).toBe('audio-capture');
    expect(node.options.processorOptions.frameSize).toBe(640); // 40 ms at 16 kHz
    node.frame(0.001);
    expect(client.sendAudio).toHaveBeenCalledOnce();
    const sent = client.sendAudio.mock.calls[0][0] as ArrayBuffer;
    expect(sent).toBeInstanceOf(ArrayBuffer);
    expect(sent.byteLength).toBe(1280); // 640 16-bit samples, no base64, no JSON
  });

  it('while the agent talks, only sends frames loud enough to be the customer', async () => {
    const client = fakeClient();
    await started(client);
    client.serverSpeaks();
    FakeAudioWorkletNode.last!.frame(0.005); // its own voice coming back through the mic
    FakeAudioWorkletNode.last!.frame(0.2); // the customer interrupting
    expect(client.sendAudio).toHaveBeenCalledOnce();
  });

  it("plays the agent's voice back-to-back on the audio clock", async () => {
    const client = fakeClient();
    await started(client);
    for (let i = 0; i < 3; i++) client.serverSpeaks();
    const starts = playback().sources.map((s) => s.startedAt);
    expect(starts[0]).toBeCloseTo(PLAYBACK_LEAD_SECONDS);
    expect(starts[1]).toBeCloseTo(PLAYBACK_LEAD_SECONDS + 0.04); // each chunk starts as the last one ends
    expect(starts[2]).toBeCloseTo(PLAYBACK_LEAD_SECONDS + 0.08);
  });

  it('after the audio runs dry, starts the next chunk a short lead from now', async () => {
    const client = fakeClient();
    await started(client);
    client.serverSpeaks();
    const context = playback();
    context.currentTime = 5; // long after the first chunk finished
    client.serverSpeaks();
    expect(context.sources[1].startedAt).toBeCloseTo(5 + PLAYBACK_LEAD_SECONDS);
  });

  it('an interruption stops everything already scheduled', async () => {
    const client = fakeClient();
    await started(client);
    for (let i = 0; i < 3; i++) client.serverSpeaks();
    client.serverSends({ type: 'bidi_interruption', reason: 'user_speech' });
    expect(playback().sources.every((s) => s.stopped)).toBe(true);
    FakeAudioWorkletNode.last!.frame(0.005); // no longer taken for the agent's own voice
    expect(client.sendAudio).toHaveBeenCalledOnce();
    client.serverSpeaks(); // the next reply starts fresh, not after the cancelled audio
    expect(playback().sources[3].startedAt).toBeCloseTo(PLAYBACK_LEAD_SECONDS);
  });

  it('applies the menu and screen snapshots the agent sends', async () => {
    const client = fakeClient();
    await started(client);
    client.serverSends({
      type: 'CUSTOM', name: 'menu',
      value: { categories: [{ categoryId: 'drinks', name: 'Drinks', sortOrder: 1 }], menuItems: { drinks: [] } },
    });
    client.serverSends({
      type: 'STATE_SNAPSHOT', epoch: 'e1', version: 1,
      snapshot: {
        highlightedCategory: 'drinks', highlightedItem: null, orderItems: [], orderTotal: 0,
        orderConfirmed: false, orderNumber: null, burgerBuilder: null,
      },
    });
    const { agentUI } = useAppStore.getState();
    expect(agentUI.categories).toHaveLength(1);
    expect(agentUI.highlightedCategory).toBe('drinks');
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
