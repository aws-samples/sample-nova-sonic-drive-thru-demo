// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useMemo } from 'react';
import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';
import type { MenuItem } from '../types';

export function ItemDetailModal() {
  const highlightedItem = useAppStore((s) => s.agentUI.highlightedItem);
  const menuItems = useAppStore((s) => s.agentUI.menuItems);

  // Look up the highlighted item from local menu data
  const item: MenuItem | null = useMemo(() => {
    if (!highlightedItem) return null;
    // Don't show detail modal when burger builder is active
    if (highlightedItem === 'custom-burger') return null;
    for (const items of Object.values(menuItems)) {
      const found = items.find((i) => i.itemId === highlightedItem);
      if (found) return found;
    }
    return null;
  }, [highlightedItem, menuItems]);

  if (!item) return null;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.5)',
      }}
    >
      <div
        style={{
          background: '#fff', color: '#333', borderRadius: 16, padding: 24,
          maxWidth: 420, width: '90%', maxHeight: '80vh', overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.2)',
        }}
      >
        <img
          src={item.imageUrl}
          alt={item.name}
          style={{ width: '100%', height: 200, objectFit: 'cover', borderRadius: 12 }}
          onError={(e) => {
            const img = e.target as HTMLImageElement;
            img.onerror = null;
            img.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="%23eee"/></svg>';
          }}
        />
        <h2 style={{ margin: '16px 0 4px', color: '#222' }}>{item.name}</h2>
        <p style={{ color: '#666', margin: '0 0 8px' }}>{item.description}</p>
        <p style={{ fontSize: '1.3em', fontWeight: 'bold', color: '#27ae60', margin: '0 0 16px' }}>
          {formatPrice(item.price)}
        </p>
      </div>
    </div>
  );
}
