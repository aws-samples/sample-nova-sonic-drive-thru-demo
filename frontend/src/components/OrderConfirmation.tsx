// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';

const CONFETTI_COLORS = ['#27ae60', '#e67e22', '#3498db', '#e74c3c', '#9b59b6', '#f1c40f'];

// Scattered once, when the module loads: rendering must not call Math.random()
const CONFETTI_PIECES = Array.from({ length: 20 }, (_, i) => ({
  id: i,
  left: `${Math.random() * 100 - 50}px`,
  color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
  delay: `${Math.random() * 0.6}s`,
  rotation: `${Math.random() * 360}deg`,
}));

function ConfettiPieces() {
  const pieces = CONFETTI_PIECES;

  return (
    <div className="confetti-container" aria-hidden="true">
      {pieces.map((p) => (
        <div
          key={p.id}
          className="confetti-piece"
          style={{
            left: p.left,
            backgroundColor: p.color,
            animationDelay: p.delay,
            transform: `rotate(${p.rotation})`,
          }}
        />
      ))}
    </div>
  );
}

export function OrderConfirmation() {
  const confirmed = useAppStore((s) => s.agentUI.orderConfirmed);
  const orderNumber = useAppStore((s) => s.agentUI.orderNumber);
  const items = useAppStore((s) => s.agentUI.orderItems);
  const total = useAppStore((s) => s.agentUI.orderTotal);

  if (!confirmed) return null;

  return (
    <section aria-label="Order confirmation" style={{ padding: '16px', textAlign: 'center', overflow: 'hidden' }}>
      <div className="confirmation-check">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <polyline points="4 12 10 18 20 6" />
        </svg>
      </div>
      <ConfettiPieces />
      <div className="confirmation-content">
        <h2>Thank you for your order!</h2>
        <p style={{ fontSize: '1.2em', fontWeight: 'bold' }}>Order #{orderNumber}</p>
        <ul style={{ listStyle: 'none', padding: 0, margin: '16px 0', textAlign: 'left' }}>
          {items.map((item) => (
            <li key={item.itemId} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #eee' }}>
              <span>{item.name} × {item.quantity}</span>
              <span>{formatPrice(item.unitPrice * item.quantity)}</span>
            </li>
          ))}
        </ul>
        <div style={{ fontWeight: 'bold', fontSize: '1.2em' }}>Total: {formatPrice(total)}</div>
      </div>
    </section>
  );
}
