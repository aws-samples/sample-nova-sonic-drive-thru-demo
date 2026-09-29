// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * Microphone capture on the audio thread (replaces the deprecated ScriptProcessorNode).
 *
 * Collects the mic input into fixed-size frames (processorOptions.frameSize samples; 640 is
 * 40 ms at 16 kHz), converts each to 16-bit PCM, and posts it to the main thread with its RMS
 * loudness: { pcm: ArrayBuffer (Int16, little-endian), rms: number }.
 *
 * It lives in public/ as plain JavaScript because worklets load as separate modules, which
 * the page's CSP (script-src 'self') allows from the site's own origin.
 */
class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.frameSize = (options && options.processorOptions && options.processorOptions.frameSize) || 640;
    this.frame = new Float32Array(this.frameSize);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true; // no input yet (or the mic was stopped); keep the node alive
    let offset = 0;
    while (offset < channel.length) {
      const n = Math.min(this.frameSize - this.filled, channel.length - offset);
      this.frame.set(channel.subarray(offset, offset + n), this.filled);
      this.filled += n;
      offset += n;
      if (this.filled === this.frameSize) {
        this.emit();
        this.filled = 0;
      }
    }
    return true;
  }

  emit() {
    const pcm = new Int16Array(this.frameSize);
    let energy = 0;
    for (let i = 0; i < this.frameSize; i++) {
      const s = Math.max(-1, Math.min(1, this.frame[i]));
      energy += s * s;
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    // Transfer, don't copy: the buffer moves to the main thread
    this.port.postMessage({ pcm: pcm.buffer, rms: Math.sqrt(energy / this.frameSize) }, [pcm.buffer]);
  }
}

registerProcessor('audio-capture', AudioCaptureProcessor);
