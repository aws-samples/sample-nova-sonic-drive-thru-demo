// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Tests the capture worklet in public/ by running its source with stand-ins for the
 * AudioWorkletGlobalScope (the browser loads it as a separate module on the audio thread).
 */
import { describe, it, expect } from 'vitest';
import source from '../../public/audio-capture-worklet.js?raw';

type Message = { pcm: ArrayBuffer; rms: number };
interface Processor {
  process(inputs: Float32Array[][]): boolean;
  port: { postMessage(m: Message, transfer?: ArrayBuffer[]): void };
}

function loadProcessor(frameSize?: number): { processor: Processor; posted: Message[] } {
  const posted: Message[] = [];
  class AudioWorkletProcessor {
    port = { postMessage: (m: Message) => posted.push(m) };
  }
  let registered: (new (options: unknown) => Processor) | null = null;
  const registerProcessor = (name: string, cls: new (options: unknown) => Processor) => {
    expect(name).toBe('audio-capture');
    registered = cls;
  };
  new Function('AudioWorkletProcessor', 'registerProcessor', source)(AudioWorkletProcessor, registerProcessor);
  const Cls = registered as unknown as new (options: unknown) => Processor;
  return { processor: new Cls({ processorOptions: frameSize ? { frameSize } : {} }), posted };
}

/** Feed `samples` through the processor in 128-sample render quanta, like the browser does. */
function feed(processor: Processor, samples: Float32Array) {
  for (let i = 0; i < samples.length; i += 128) {
    expect(processor.process([[samples.subarray(i, i + 128)]])).toBe(true);
  }
}

describe('audio capture worklet', () => {
  it('emits one 640-sample frame per 40 ms of audio', () => {
    const { processor, posted } = loadProcessor(640);
    feed(processor, new Float32Array(16000)); // 1 s at 16 kHz
    expect(posted).toHaveLength(25);
    expect(posted.every((m) => new Int16Array(m.pcm).length === 640)).toBe(true);
  });

  it('keeps samples in order across render quanta and converts them to 16-bit PCM', () => {
    const { processor, posted } = loadProcessor(640);
    const samples = new Float32Array(1280).map((_, i) => ((i % 200) - 100) / 100); // ramps from -1 to 0.99
    feed(processor, samples);
    const pcm = [...new Int16Array(posted[0].pcm), ...new Int16Array(posted[1].pcm)];
    expect(pcm[0]).toBe(-32768);
    expect(pcm[100]).toBe(0);
    expect(pcm[199]).toBe(Math.trunc(0.99 * 0x7fff));
    expect(pcm[200]).toBe(-32768); // the ramp restarts, including across the frame boundary at 640
    expect(pcm[639 + 1]).toBe(Math.trunc(((640 % 200) - 100) / 100 * 0x7fff));
  });

  it('clips out-of-range samples and reports loudness', () => {
    const { processor, posted } = loadProcessor(640);
    feed(processor, new Float32Array(640).fill(2));
    expect(new Int16Array(posted[0].pcm)[0]).toBe(0x7fff);
    expect(posted[0].rms).toBeCloseTo(1);
    feed(processor, new Float32Array(640));
    expect(posted[1].rms).toBe(0);
  });

  it('defaults to 40 ms frames, and waits out missing input', () => {
    const { processor, posted } = loadProcessor();
    expect(processor.process([[]])).toBe(true);
    expect(processor.process([])).toBe(true);
    feed(processor, new Float32Array(640));
    expect(posted).toHaveLength(1);
  });
});
