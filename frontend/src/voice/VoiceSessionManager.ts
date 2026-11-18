// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Voice session manager: mic capture, playback of the agent's voice, interruptions, and the
 * agent's screen messages.
 *
 * Audio goes both ways as binary WebSocket frames of raw AUDIO_FORMAT PCM; the agent's other
 * messages are JSON (see ../protocol/messages.ts, generated from agent/protocol.py).
 */

import type { AgentCoreWebSocketClient } from './WebSocketClient';
import { useAppStore } from '../store/appStore';
import { AUDIO_FORMAT } from '../protocol/messages';
import type { ServerMessage, SessionEnded } from '../protocol/messages';

export type SessionEndReason = SessionEnded['reason'];

const SAMPLE_RATE = AUDIO_FORMAT.sampleRate; // both ways; the agent configures Nova Sonic for it
// 40 ms mic frames. Smaller frames reach the model sooner (the old ScriptProcessor sent 256 ms
// at a time), at 25 messages a second; the agent rate-limits by bytes, so that's fine.
export const FRAME_SAMPLES = 640;
// While the agent is talking, frames quieter than this are taken for its own voice coming
// back through the mic, and not sent.
const ECHO_GATE_RMS = 0.015;
// When the agent starts talking (or its audio ran dry), the first chunk starts this far in
// the future, so the chunks after it arrive in time to play back-to-back.
export const PLAYBACK_LEAD_SECONDS = 0.05;

// Waits before each reconnect attempt after an unexpected drop; then the session is given up.
const RECONNECT_DELAYS_MS = [250, 1000, 2000, 4000, 8000];

const END_MESSAGES: Record<SessionEndReason, string> = {
  'order-complete': 'Thank you for your order!',
  'idle-timeout': 'Your session ended after a period of silence. Start again whenever you are ready.',
  'conversation-ended': 'Thank you for visiting!',
  'agent-error': 'Sorry, the voice assistant ran into a problem. Please start again.',
};
const DROPPED_MESSAGE = 'The voice session was disconnected. Start again to continue.';

export class VoiceSessionManager {
  private client: AgentCoreWebSocketClient;
  private mediaStream: MediaStream | null = null;
  private captureContext: AudioContext | null = null;
  private playbackContext: AudioContext | null = null;
  // Agent audio already handed to the audio clock, and when the last of it ends (in
  // playbackContext time). Each chunk starts exactly where the previous one ends.
  private scheduledSources = new Set<AudioBufferSourceNode>();
  private nextStartTime = 0;
  private active = false;
  private reconnecting = false;
  // Reconnect attempts used since the conversation last worked. Only reset once the agent is
  // heard again, so a connection that opens and then fails straight away can't retry forever.
  private reconnectAttempts = 0;
  private isSpeaking = false; // true while agent audio is playing
  private endReason: SessionEndReason | null = null; // set when the agent says why it is ending the session
  private onEnded: ((message: string, reason: SessionEndReason | null) => void) | null;
  // One agent session per order: kept across reconnects so the order survives a dropped connection
  private sessionId = '';
  private runtimeArn = '';
  private region = '';
  private getToken: () => Promise<string> = async () => '';

  /**
   * @param onEnded Called when the session ends without Stop being pressed: with a user-facing
   *   message, and the agent's reason ('order-complete', 'idle-timeout', 'conversation-ended')
   *   or null if the connection dropped and could not be restored.
   */
  constructor(client: AgentCoreWebSocketClient, onEnded?: (message: string, reason: SessionEndReason | null) => void) {
    this.client = client;
    this.onEnded = onEnded ?? null;
  }

  /**
   * @param getToken Returns a current access token; called for every connection, so a
   *   reconnect late in a long order doesn't use an expired one.
   */
  async startSession(
    runtimeArn: string,
    region: string,
    getToken: () => Promise<string>,
  ): Promise<void> {
    this.runtimeArn = runtimeArn;
    this.region = region;
    this.getToken = getToken;
    this.sessionId = crypto.randomUUID();

    // 1. Request microphone
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: AUDIO_FORMAT.channels, sampleRate: SAMPLE_RATE, echoCancellation: true, noiseSuppression: true },
      });
    } catch (err: unknown) {
      useAppStore.getState().setMicPermission('denied');
      throw new Error('Microphone access is required for voice ordering.');
    }
    useAppStore.getState().setMicPermission('granted');

    // 2. Register event handler BEFORE connecting so we don't miss the initial state
    this.playbackContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    this.client.onMessage((message) => this.handleMessage(message));
    this.client.onAudio((pcm) => this.handleAudio(pcm));

    // When the agent ends the session (it says why first), release the mic and tell the user.
    // Any other close is a dropped connection: reconnect to the same session and carry on.
    this.client.onDisconnect(() => {
      if (!this.active || this.reconnecting) return; // Stop was pressed, or a retry failed
      if (this.endReason) {
        this.finish(END_MESSAGES[this.endReason] ?? DROPPED_MESSAGE, this.endReason);
      } else {
        void this.reconnect();
      }
    });

    // 3. Connect WebSocket. The agent sends the menu and screen, then greets the customer.
    await this.client.connect(runtimeArn, region, await getToken(), this.sessionId);

    // 4. Capture the mic on the audio thread in 40 ms frames → send each as a binary frame
    try {
      this.captureContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      await this.captureContext.audioWorklet.addModule(`${import.meta.env.BASE_URL}audio-capture-worklet.js`);
      const source = this.captureContext.createMediaStreamSource(this.mediaStream);
      const capture = new AudioWorkletNode(this.captureContext, 'audio-capture', {
        numberOfInputs: 1,
        numberOfOutputs: 0, // nothing to play: it only reads the mic
        channelCount: 1,
        processorOptions: { frameSize: FRAME_SAMPLES },
      });
      capture.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) =>
        this.sendAudioFrame(e.data.pcm, e.data.rms);
      source.connect(capture);
    } catch (err) {
      this.endSession(); // don't leave the connection open without a microphone
      throw new Error(`Could not start the microphone: ${(err as Error).message}`);
    }

    // 5. Mark active
    this.active = true;
    useAppStore.getState().setVoiceSession(true);
    useAppStore.getState().setListening(true);
  }

  /** Send one captured mic frame (16-bit PCM) to the agent, as is. */
  sendAudioFrame(pcm: ArrayBuffer, rms: number): void {
    if (!this.active) return;
    // Simple energy gate while the agent is talking: quiet speaker bleed-through would
    // otherwise interrupt it, but a customer who actually speaks up still can.
    if (this.isSpeaking && rms < ECHO_GATE_RMS) return;
    this.client.sendAudio(pcm);
  }

  /** Reconnect to the same agent session after an unexpected drop, keeping the microphone open. */
  private async reconnect(): Promise<void> {
    this.reconnecting = true;
    useAppStore.getState().setReconnecting(true);
    this.stopPlayback(); // the agent's interrupted reply won't continue
    while (this.reconnectAttempts < RECONNECT_DELAYS_MS.length) {
      const delay = RECONNECT_DELAYS_MS[this.reconnectAttempts++];
      await new Promise((resolve) => setTimeout(resolve, delay));
      if (!this.active) return; // Stop was pressed meanwhile
      try {
        await this.client.connect(this.runtimeArn, this.region, await this.getToken(), this.sessionId);
        if (!this.active) {
          this.client.disconnect();
          return;
        }
        console.log('[Voice] Reconnected to session');
        this.reconnecting = false;
        useAppStore.getState().setReconnecting(false);
        return;
      } catch (err) {
        console.warn('[Voice] Reconnect attempt failed:', err);
      }
    }
    this.reconnecting = false;
    this.finish(DROPPED_MESSAGE, null);
  }

  private finish(message: string, reason: SessionEndReason | null): void {
    this.endSession();
    this.onEnded?.(message, reason);
  }

  endSession(): void {
    this.active = false; // first, so the close below isn't taken for a dropped connection
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((t) => t.stop());
      this.mediaStream = null;
    }
    if (this.captureContext) {
      this.captureContext.close().catch(() => {});
      this.captureContext = null;
    }
    if (this.playbackContext) {
      this.playbackContext.close().catch(() => {});
      this.playbackContext = null;
    }
    this.scheduledSources.clear();
    this.nextStartTime = 0;
    this.isSpeaking = false;
    this.client.disconnect();
    useAppStore.getState().endVoiceSession();
  }

  isActive(): boolean {
    return this.active;
  }

  /** The agent's voice: one binary frame of AUDIO_FORMAT PCM. */
  private handleAudio(pcm: ArrayBuffer): void {
    this.reconnectAttempts = 0; // the conversation is working again
    this.queueAudio(pcm);
  }

  private handleMessage(message: ServerMessage): void {
    switch (message.type) {
      case 'bidi_interruption':
        // Stop the agent's voice immediately, including what is already scheduled
        this.stopPlayback();
        break;

      case 'STATE_SNAPSHOT': {
        // Everything on screen apart from the menu, sent whole after every change
        const { epoch, version, snapshot } = message;
        if (!useAppStore.getState().applySnapshot(epoch, version, snapshot)) {
          console.warn('[Voice] Ignored an out-of-date screen snapshot:', version);
        }
        break;
      }

      case 'CUSTOM':
        if (message.name === 'menu') {
          useAppStore.getState().applyMenu(message.value);
        } else if (message.name === 'session_ended') {
          // Sent by the agent just before it closes the socket
          this.endReason = message.value.reason;
        }
        break;

      default:
        break; // a message type this build doesn't know
    }
  }

  private stopPlayback(): void {
    for (const source of this.scheduledSources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // already stopped
      }
    }
    this.scheduledSources.clear();
    this.nextStartTime = 0;
    this.isSpeaking = false;
  }

  /**
   * Schedule a chunk of the agent's voice to start exactly when the previous one ends, on the
   * audio clock. (Starting each chunk from the previous one's `onended` left a gap between
   * chunks: the event fires on the main thread, after the audio has already run out.)
   */
  private queueAudio(pcm: ArrayBuffer): void {
    if (!this.playbackContext || this.playbackContext.state === 'closed') {
      this.playbackContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      this.nextStartTime = 0;
    }
    const context = this.playbackContext;

    // Resume if browser suspended the AudioContext (e.g. tab backgrounded)
    if (context.state === 'suspended') {
      void context.resume();
    }

    const samples = new Int16Array(pcm, 0, pcm.byteLength >> 1); // little-endian, as the agent sends it
    if (samples.length === 0) return;
    const float32 = new Float32Array(samples.length);
    for (let i = 0; i < samples.length; i++) {
      float32[i] = samples[i] / (samples[i] < 0 ? 0x8000 : 0x7fff);
    }
    const buffer = context.createBuffer(AUDIO_FORMAT.channels, float32.length, SAMPLE_RATE);
    buffer.getChannelData(0).set(float32);

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    // Back-to-back with what is still to play; if it has all played, a short lead from now
    const startAt = this.nextStartTime > context.currentTime
      ? this.nextStartTime
      : context.currentTime + PLAYBACK_LEAD_SECONDS;
    source.onended = () => {
      this.scheduledSources.delete(source);
      if (this.scheduledSources.size === 0) this.isSpeaking = false;
    };
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
    this.scheduledSources.add(source);
    this.isSpeaking = true;
  }
}
