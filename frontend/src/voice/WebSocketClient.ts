// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/**
 * WebSocket client for AgentCore using OAuth via Sec-WebSocket-Protocol.
 * All communication is JSON — audio is base64-encoded inside typed events.
 */

export type WebSocketState = 'connecting' | 'connected' | 'disconnected';

export interface BidiEvent {
  type: string;
  [key: string]: unknown;
}

export interface AgentCoreWebSocketClient {
  /**
   * Open a connection. Reusing a sessionId reaches the same agent session (AgentCore routes
   * each runtime session ID to the same microVM), which is how a dropped connection resumes.
   * AgentCore requires session IDs of at least 33 characters; a UUID has 36.
   */
  connect(runtimeArn: string, region: string, jwtToken: string, sessionId: string): Promise<void>;
  disconnect(): void;
  send(event: BidiEvent): void;
  onEvent(callback: (event: BidiEvent) => void): void;
  onDisconnect(callback: () => void): void;
  getState(): WebSocketState;
}

export function createWebSocketClient(): AgentCoreWebSocketClient {
  let ws: WebSocket | null = null;
  let state: WebSocketState = 'disconnected';
  const eventCallbacks: Array<(event: BidiEvent) => void> = [];
  const disconnectCallbacks: Array<() => void> = [];

  return {
    async connect(runtimeArn, region, jwtToken, sessionId) {
      state = 'connecting';

      const encodedArn = encodeURIComponent(runtimeArn);
      const url = `wss://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodedArn}/ws?qualifier=DEFAULT&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id=${encodeURIComponent(sessionId)}`;

      // OAuth via Sec-WebSocket-Protocol: base64url-encode the token
      const base64url = btoa(jwtToken)
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=/g, '');
      const protocols = [
        `base64UrlBearerAuthorization.${base64url}`,
        'base64UrlBearerAuthorization',
      ];

      console.log('[WS] Connecting to:', url.substring(0, 120) + '...');

      return new Promise<void>((resolve, reject) => {
        const socket = new WebSocket(url, protocols);
        ws = socket;
        // Events from a socket this client has since replaced or dropped are ignored.
        const current = () => ws === socket;

        socket.onopen = () => {
          if (!current()) return;
          console.log('[WS] Connected');
          state = 'connected';
          resolve();
        };

        socket.onerror = (event) => {
          console.error('[WS] Error:', event);
          if (!current()) return;
          state = 'disconnected';
          reject(new Error('WebSocket connection failed'));
        };

        socket.onclose = (event) => {
          console.log('[WS] Closed:', event.code, event.reason, 'clean:', event.wasClean);
          if (!current()) return;
          state = 'disconnected';
          reject(new Error('WebSocket closed before it opened')); // no-op once opened
          for (const cb of disconnectCallbacks) cb();
        };

        socket.onmessage = (msg) => {
          if (!current()) return;
          try {
            const event = JSON.parse(msg.data) as BidiEvent;
            for (const cb of eventCallbacks) cb(event);
          } catch { /* ignore non-JSON */ }
        };
      });
    },

    disconnect() {
      const socket = ws;
      ws = null;
      state = 'disconnected';
      socket?.close();
    },

    send(event) {
      // readyState, not our own state: it turns CLOSING as soon as the server starts closing,
      // before onclose runs, and sending then only logs browser errors.
      if (ws && state === 'connected' && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(event));
      }
    },

    onEvent(callback) {
      eventCallbacks.push(callback);
    },

    onDisconnect(callback) {
      disconnectCallbacks.push(callback);
    },

    getState() {
      return state;
    },
  };
}
