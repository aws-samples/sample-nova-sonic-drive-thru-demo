// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Voice session manager using Strands BidiAgent JSON protocol.
 * Audio is base64-encoded inside JSON events — no raw binary frames.
 * Handles mic capture, audio playback, interruptions, and UI_Events.
 */

import type { AgentCoreWebSocketClient, BidiEvent } from './WebSocketClient';
import { useAppStore } from '../store/appStore';

export class VoiceSessionManager {
  private client: AgentCoreWebSocketClient;
  private mediaStream: MediaStream | null = null;
  private captureContext: AudioContext | null = null;
  private playbackContext: AudioContext | null = null;
  private audioQueue: AudioBuffer[] = [];
  private isPlaying = false;
  private active = false;
  private currentSource: AudioBufferSourceNode | null = null;
  private isSpeaking = false; // true while agent audio is playing
  private endReason: string | null = null; // set when the agent says why it is ending the session
  private onEnded: ((message: string, reason: string | null) => void) | null;

  /**
   * @param onEnded Called when the session ends without Stop being pressed: with a user-facing
   *   message, and the agent's reason ('order-complete', 'idle-timeout') or null if the
   *   connection dropped.
   */
  constructor(client: AgentCoreWebSocketClient, onEnded?: (message: string, reason: string | null) => void) {
    this.client = client;
    this.onEnded = onEnded ?? null;
  }

  async startSession(
    runtimeArn: string,
    region: string,
    jwtToken: string,
  ): Promise<void> {
    // 1. Request microphone
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });
    } catch (err: unknown) {
      useAppStore.getState().setMicPermission('denied');
      throw new Error('Microphone access is required for voice ordering.');
    }
    useAppStore.getState().setMicPermission('granted');

    // 2. Register event handler BEFORE connecting so we don't miss the initial state
    this.playbackContext = new AudioContext({ sampleRate: 16000 });
    this.client.onEvent((event: BidiEvent) => this.handleEvent(event));

    // The server can close the session (e.g. after a period of silence). Release the mic and
    // tell the user, rather than showing "Listening…" on a closed socket.
    this.client.onDisconnect(() => {
      if (!this.active) return; // closed by endSession(), i.e. the user pressed Stop
      this.endSession();
      const messages: Record<string, string> = {
        'order-complete': 'Thank you for your order!',
        'idle-timeout': 'Your session ended after a period of silence. Start again whenever you are ready.',
      };
      this.onEnded?.(
        messages[this.endReason ?? ''] ?? 'The voice session was disconnected. Start again to continue.',
        this.endReason,
      );
    });

    // 3. Connect WebSocket
    await this.client.connect(runtimeArn, region, jwtToken);

    // 4. Send initial greeting to trigger the agent
    this.client.send({
      type: 'bidi_text_input',
      text: 'Hello',
      role: 'user',
    });

    // 5. Set up audio capture → send as bidi_audio_input JSON events
    this.captureContext = new AudioContext({ sampleRate: 16000 });
    const source = this.captureContext.createMediaStreamSource(this.mediaStream);
    const processor = this.captureContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e: AudioProcessingEvent) => {
      if (!this.active) return;

      const float32 = e.inputBuffer.getChannelData(0);

      // Simple energy gate: only send audio if it's loud enough to be real speech.
      // This prevents quiet speaker bleed-through from triggering interruptions
      // while still allowing the user to interrupt by actually speaking.
      if (this.isSpeaking) {
        let energy = 0;
        for (let i = 0; i < float32.length; i++) {
          energy += float32[i] * float32[i];
        }
        const rms = Math.sqrt(energy / float32.length);
        // Threshold: RMS below 0.015 is likely echo/background, above is real speech
        if (rms < 0.015) return;
      }

      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      const base64 = btoa(String.fromCharCode(...new Uint8Array(int16.buffer)));
      this.client.send({
        type: 'bidi_audio_input',
        audio: base64,
        format: 'pcm',
        sample_rate: 16000,
        channels: 1,
      });
    };

    source.connect(processor);
    processor.connect(this.captureContext.destination);

    // 5. Mark active
    this.active = true;
    useAppStore.getState().setVoiceSession(true);
    useAppStore.getState().setListening(true);
  }

  endSession(): void {
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
    this.audioQueue = [];
    this.isPlaying = false;
    this.client.disconnect();
    this.active = false;
    useAppStore.getState().endVoiceSession();
  }

  isActive(): boolean {
    return this.active;
  }

  private handleEvent(event: BidiEvent): void {
    switch (event.type) {
      case 'bidi_audio_stream':
        this.isSpeaking = true;
        this.queueAudio(event.audio as string, (event.sample_rate as number) || 16000);
        break;

      case 'bidi_interruption':
        // Stop the currently playing audio immediately
        this.isSpeaking = false;
        if (this.currentSource) {
          this.currentSource.onended = null;
          this.currentSource.stop();
          this.currentSource = null;
        }
        this.audioQueue = [];
        this.isPlaying = false;
        if (this.playbackContext) {
          this.playbackContext.close().catch(() => {});
          this.playbackContext = new AudioContext({ sampleRate: 16000 });
        }
        break;

      case 'bidi_transcript_stream':
        break;

      case 'session_ended':
        // Sent by the agent just before it closes the socket
        this.endReason = typeof event.reason === 'string' ? event.reason : null;
        break;

      case 'ui_state_update':
        // Agent sent the full UI state — apply it directly
        console.log('[Voice] UI state update received, categories:', (event.state as any)?.categories?.length);
        if (event.state && typeof event.state === 'object') {
          useAppStore.getState().applyAgentUIState(event.state as any);
        }
        break;

      default:
        break;
    }
  }

  private queueAudio(base64Audio: string, sampleRate: number): void {
    if (!this.playbackContext || this.playbackContext.state === 'closed') {
      this.playbackContext = new AudioContext({ sampleRate });
    }

    // Resume if browser suspended the AudioContext (e.g. tab backgrounded)
    if (this.playbackContext.state === 'suspended') {
      this.playbackContext.resume();
    }

    const binary = atob(base64Audio);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const pcm = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(pcm.length);
    for (let i = 0; i < pcm.length; i++) {
      float32[i] = pcm[i] / (pcm[i] < 0 ? 0x8000 : 0x7fff);
    }

    const buffer = this.playbackContext.createBuffer(1, float32.length, sampleRate);
    buffer.getChannelData(0).set(float32);
    this.audioQueue.push(buffer);

    if (!this.isPlaying) this.playNext();
  }

  private playNext(): void {
    if (this.audioQueue.length === 0 || !this.playbackContext || this.playbackContext.state === 'closed') {
      this.isPlaying = false;
      this.isSpeaking = false;
      this.currentSource = null;
      return;
    }

    this.isPlaying = true;
    const buffer = this.audioQueue.shift()!;
    const source = this.playbackContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.playbackContext.destination);
    source.onended = () => this.playNext();
    this.currentSource = source;
    source.start();
  }
}
