// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useRef, useCallback, useState } from 'react';
import { useAuthenticator } from '@aws-amplify/ui-react';
import { fetchAuthSession } from 'aws-amplify/auth';
import { MenuDisplay, OrderSummaryPanel, OrderConfirmation, ItemDetailModal, BurgerBuilder, DebugPanel } from './components';
import { useAppStore } from './store';
import { createWebSocketClient, VoiceSessionManager } from './voice';
import { getRuntimeConfig } from './config';
import { formatPrice } from './utils/formatPrice';

// How long the confirmation stays up after the agent ends a completed order, before the
// screen returns to the welcome state for the next car.
const CONFIRMATION_DISPLAY_MS = 8000;

export default function App() {
  const { signOut } = useAuthenticator();

  const sessionActive = useAppStore((s) => s.voice.sessionActive);
  const listening = useAppStore((s) => s.voice.listening);
  const reconnecting = useAppStore((s) => s.voice.reconnecting);
  const micPermission = useAppStore((s) => s.voice.micPermission);
  const orderConfirmed = useAppStore((s) => s.agentUI.orderConfirmed);
  const hasMenu = useAppStore((s) => s.agentUI.categories.length > 0);
  // Sent by the agent with the menu, so the price shown is the price charged
  const burgerBasePrice = useAppStore((s) => s.agentUI.customBurger?.basePrice ?? null);

  const debugMode = new URLSearchParams(window.location.search).has('debug');

  const voiceManagerRef = useRef<VoiceSessionManager | null>(null);
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  // The agent ended the session. A completed order stays on screen briefly; a customer who
  // went quiet (drove off) gets the welcome screen straight away. Either way the next car
  // starts from a clean screen.
  const handleSessionEnded = useCallback((message: string, reason: string | null) => {
    voiceManagerRef.current = null;
    if (reason === 'order-complete') {
      resetTimerRef.current = setTimeout(() => useAppStore.getState().resetAgentUI(), CONFIRMATION_DISPLAY_MS);
    } else if (reason === 'idle-timeout') {
      useAppStore.getState().resetAgentUI();
      setVoiceNotice(message);
    } else {
      setVoiceNotice(message);
    }
  }, []);

  const handleStartVoice = useCallback(async () => {
    setVoiceError(null);
    setVoiceNotice(null);
    if (resetTimerRef.current) {
      clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
    useAppStore.getState().resetAgentUI(); // a new session is a new order
    setConnecting(true);
    try {
      const config = getRuntimeConfig();
      const getToken = async () => {
        const session = await fetchAuthSession(); // refreshes the token if it has expired
        const token = session.tokens?.accessToken?.toString();
        if (!token) throw new Error('No access token available');
        return token;
      };
      const client = createWebSocketClient();
      const manager = new VoiceSessionManager(client, handleSessionEnded);
      voiceManagerRef.current = manager;
      await manager.startSession(config.agentRuntimeArn, config.awsRegion, getToken);
    } catch (err) {
      setVoiceError((err as Error).message);
    } finally {
      setConnecting(false);
    }
  }, [handleSessionEnded]);

  const handleStopVoice = useCallback(() => {
    if (voiceManagerRef.current) {
      voiceManagerRef.current.endSession();
      voiceManagerRef.current = null;
    }
  }, []);

  // Order confirmed screen
  if (orderConfirmed) {
    return (
      <div style={{ maxWidth: 600, margin: '0 auto', padding: 16 }}>
        {debugMode && <DebugPanel />}
        <OrderConfirmation />
      </div>
    );
  }

  // Landing page — no voice session yet
  if (!sessionActive && !hasMenu) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
        {debugMode && <DebugPanel />}
        <h1 style={{ fontSize: '2.5em', marginBottom: 8 }}>🍔 Drive-Thru</h1>
        <p style={{ color: '#666', fontSize: '1.1em', marginBottom: 32 }}>Voice-powered ordering</p>

        <button
          onClick={handleStartVoice}
          disabled={connecting}
          style={{
            padding: '20px 48px', fontSize: '1.3em', fontWeight: 'bold',
            borderRadius: 16, border: 'none', cursor: connecting ? 'wait' : 'pointer',
            background: connecting ? '#95a5a6' : '#27ae60', color: '#fff',
            boxShadow: '0 4px 16px rgba(39,174,96,0.3)',
            transition: 'background 0.2s',
          }}
        >
          {connecting ? 'Connecting…' : '🎙️ Start Your Order'}
        </button>

        {micPermission === 'denied' && (
          <p style={{ color: 'red', marginTop: 16 }}>Microphone access denied. Please allow it and try again.</p>
        )}
        {voiceError && (
          <p style={{ color: 'red', marginTop: 16 }}>{voiceError}</p>
        )}
        {voiceNotice && (
          <p role="status" style={{ color: '#666', marginTop: 16 }}>{voiceNotice}</p>
        )}

        <button onClick={signOut} type="button" style={{ marginTop: 48, color: '#999', background: 'none', border: 'none', cursor: 'pointer' }}>
          Sign Out
        </button>
      </div>
    );
  }

  // Active session — menu + order
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: 16 }}>
      {debugMode && <DebugPanel />}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>🍔 Drive-Thru</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          {sessionActive ? (
            <button onClick={handleStopVoice} type="button">Stop</button>
          ) : (
            <button onClick={handleStartVoice} type="button" disabled={connecting}>
              {connecting ? 'Connecting…' : '🎙️ Start again'}
            </button>
          )}
        </div>
      </div>

      {reconnecting ? (
        <div style={{ marginBottom: 12, color: '#e67e22', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <span role="status">Reconnecting…</span>
        </div>
      ) : listening && (
        <div style={{ marginBottom: 12, color: 'green', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <span role="status" aria-label="Listening">🎙️ Listening…</span>
        </div>
      )}
      {voiceError && <p style={{ color: 'red' }}>{voiceError}</p>}
      {voiceNotice && <p role="status" style={{ color: '#666' }}>{voiceNotice}</p>}

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        {/* Build Your Own — left sidebar (only show when menu is loaded) */}
        {hasMenu && (
        <div style={{ width: 180, flexShrink: 0, position: 'sticky', top: 16 }}>
          {/* Display only: the customer asks for a custom burger by voice */}
          <div
            style={{
              background: '#fff',
              border: '1px solid #eee',
              borderRadius: 12,
              padding: '14px 16px',
              textAlign: 'center',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: '0.9em', color: '#333' }}>or Build Your Own Burger</div>
            {burgerBasePrice !== null && (
              <div style={{ marginTop: 6, fontSize: '0.75em', color: '#27ae60', fontWeight: 600 }}>From {formatPrice(burgerBasePrice)}</div>
            )}
            <div style={{ marginTop: 6, fontSize: '0.7em', color: '#888' }}>Just ask to build your own</div>
          </div>
        </div>
        )}

        {/* Menu */}
        <div style={{ flex: 2 }}><MenuDisplay /></div>

        {/* Order summary */}
        <div style={{ flex: 1, position: 'sticky', top: 16, maxHeight: 'calc(100vh - 32px)', overflowY: 'auto' }}>
          <OrderSummaryPanel />
        </div>
      </div>

      <ItemDetailModal />
      <BurgerBuilder />
    </div>
  );
}
