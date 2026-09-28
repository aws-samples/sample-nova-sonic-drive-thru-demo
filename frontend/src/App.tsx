// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useRef, useCallback, useState } from 'react';
import { useAuthenticator } from '@aws-amplify/ui-react';
import { fetchAuthSession } from 'aws-amplify/auth';
import { MenuDisplay, OrderSummaryPanel, OrderConfirmation, ItemDetailModal, BurgerBuilder, DebugPanel } from './components';
import { useAppStore } from './store';
import { createWebSocketClient, VoiceSessionManager } from './voice';
import { getRuntimeConfig } from './config';
import type { MenuItem } from './types';
import { formatPrice } from './utils/formatPrice';

// Build-your-own base price in fils (100 fils = 1 AED); mirrors agent/order_tools.py.
const CUSTOM_BURGER_BASE_PRICE = 3300;

export default function App() {
  const { signOut } = useAuthenticator();

  const sessionActive = useAppStore((s) => s.voice.sessionActive);
  const listening = useAppStore((s) => s.voice.listening);
  const micPermission = useAppStore((s) => s.voice.micPermission);
  const orderConfirmed = useAppStore((s) => s.agentUI.orderConfirmed);
  const hasMenu = useAppStore((s) => s.agentUI.categories.length > 0);

  const debugMode = new URLSearchParams(window.location.search).has('debug');

  const voiceManagerRef = useRef<VoiceSessionManager | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const handleStartVoice = useCallback(async () => {
    setVoiceError(null);
    setConnecting(true);
    try {
      const config = getRuntimeConfig();
      const session = await fetchAuthSession();
      const token = session.tokens?.accessToken?.toString();
      if (!token) throw new Error('No access token available');
      const client = createWebSocketClient();
      const manager = new VoiceSessionManager(client);
      voiceManagerRef.current = manager;
      await manager.startSession(config.agentRuntimeArn, config.awsRegion, token);
    } catch (err) {
      setVoiceError((err as Error).message);
    } finally {
      setConnecting(false);
    }
  }, []);

  const handleStopVoice = useCallback(() => {
    if (voiceManagerRef.current) {
      voiceManagerRef.current.endSession();
      voiceManagerRef.current = null;
    }
  }, []);

  const handleItemClick = useCallback((item: MenuItem) => {
    const current = useAppStore.getState().agentUI;
    useAppStore.getState().applyAgentUIState({
      ...current,
      highlightedItem: item.itemId,
    });
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
          {sessionActive && (
            <button onClick={handleStopVoice} type="button">Stop</button>
          )}

        </div>
      </div>

      {listening && (
        <div style={{ marginBottom: 12, color: 'green', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <span role="status" aria-label="Listening">🎙️ Listening…</span>
        </div>
      )}
      {voiceError && <p style={{ color: 'red' }}>{voiceError}</p>}

      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        {/* Build Your Own — left sidebar (only show when menu is loaded) */}
        {hasMenu && (
        <div style={{ width: 180, flexShrink: 0, position: 'sticky', top: 16 }}>
          <div
            onClick={() => {
              useAppStore.getState().applyAgentUIState({
                ...useAppStore.getState().agentUI,
                burgerBuilder: { active: true, patty: null, toppings: [], sauces: [], price: CUSTOM_BURGER_BASE_PRICE },
              });
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click(); }}
            style={{
              cursor: 'pointer',
              background: '#fff',
              border: '1px solid #eee',
              borderRadius: 12,
              padding: '14px 16px',
              textAlign: 'center',
              transition: 'transform 0.2s, box-shadow 0.2s',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.02)'; e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.08)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = 'none'; }}
          >
            <div style={{ fontWeight: 600, fontSize: '0.9em', color: '#333' }}>or Build Your Own Burger</div>
            <div style={{ marginTop: 6, fontSize: '0.75em', color: '#27ae60', fontWeight: 600 }}>From {formatPrice(CUSTOM_BURGER_BASE_PRICE)}</div>
          </div>
        </div>
        )}

        {/* Menu */}
        <div style={{ flex: 2 }}><MenuDisplay onItemClick={handleItemClick} /></div>

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
