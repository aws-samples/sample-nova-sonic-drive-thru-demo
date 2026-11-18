import { useAppStore } from '../store';
import { formatPrice } from '../utils/formatPrice';
import type { BurgerBuilderState } from '../types';

const TOPPING_ICONS: Record<string, string> = {
  'beef patty': '🥩',
  'chicken patty': '🍗',
  'american cheese': '🧀',
  'cheddar cheese': '🧀',
  'pepper jack cheese': '🧀',
  'swiss cheese': '🧀',
  'bacon': '🥓',
  'avocado': '🥑',
  'fried egg': '🍳',
  'lettuce': '🥬',
  'tomato': '🍅',
  'onion': '🧅',
  'pickles': '🥒',
  'jalapeños': '🌶️',
  'mushrooms': '🍄',
  'ketchup': '🔴',
  'mustard': '🟡',
  'mayo': '⚪',
  'bbq sauce': '🟤',
  'chipotle mayo': '🟠',
  'special sauce': '✨',
};

export function BurgerBuilder() {
  const builder = useAppStore((s) => s.agentUI.burgerBuilder);
  // Add-on prices in fils, sent by the agent with the menu (agent/custom_burger.py)
  const toppingPrices = useAppStore((s) => s.agentUI.customBurger?.toppings);
  const priceOf = (topping: string) => toppingPrices?.find((t) => t.name === topping)?.price;

  if (!builder || !builder.active) return null;

  const hasIngredients = (builder.patty && builder.patty !== 'null') || builder.toppings.length > 0 || builder.sauces.length > 0;

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backgroundColor: 'rgba(0,0,0,0.6)',
        backdropFilter: 'blur(4px)',
      }}
    >
      <div
        style={{
          background: 'linear-gradient(180deg, #fffbf0 0%, #fff 40%)',
          color: '#333', borderRadius: 24, padding: 0,
          maxWidth: 440, width: '92%', maxHeight: '88vh', overflow: 'hidden',
          boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
          display: 'flex', flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '24px 24px 16px',
          textAlign: 'center',
          borderBottom: '1px solid #f0e8d8',
        }}>
          <div style={{ fontSize: '2.5em', marginBottom: 4 }}>🍔</div>
          <h2 style={{ margin: '0 0 4px', color: '#222', fontSize: '1.4em', fontWeight: 700 }}>
            Build Your Burger
          </h2>
          <p style={{ color: '#999', margin: 0, fontSize: '0.85em' }}>
            Tell me what you'd like on it
          </p>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px 24px' }}>
          {/* Burger visualization */}
          <BurgerStack builder={builder} />

          {/* Ingredients */}
          {hasIngredients ? (
            <div style={{ marginTop: 20 }}>
              {builder.patty && builder.patty !== 'null' && (
                <IngredientRow icon={TOPPING_ICONS[builder.patty]} label={builder.patty} tag="base" />
              )}
              {builder.toppings.map((t, i) => (
                <IngredientRow
                  key={i}
                  icon={TOPPING_ICONS[t] || '•'}
                  label={t}
                  price={priceOf(t)}
                />
              ))}
              {builder.sauces.map((s, i) => (
                <IngredientRow key={i} icon={TOPPING_ICONS[s] || '💧'} label={s} tag="free" />
              ))}
            </div>
          ) : (
            <div style={{
              textAlign: 'center', padding: '24px 16px',
              background: '#fafafa', borderRadius: 12, marginTop: 16,
            }}>
              <p style={{ color: '#bbb', margin: 0, fontSize: '0.9em' }}>
                🎙️ Start by choosing a patty...
              </p>
            </div>
          )}
        </div>

        {/* Footer — price */}
        <div style={{
          padding: '16px 24px',
          borderTop: '1px solid #f0e8d8',
          background: '#fafaf7',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          borderRadius: '0 0 24px 24px',
        }}>
          <span style={{ fontSize: '0.85em', color: '#888', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Total
          </span>
          <span style={{ fontSize: '1.5em', fontWeight: 800, color: '#27ae60' }}>
            {formatPrice(builder.price)}
          </span>
        </div>
      </div>
    </div>
  );
}

function BurgerStack({ builder }: { builder: BurgerBuilderState }) {
  const layers: { emoji: string; color: string; width: number }[] = [];

  // Top bun
  layers.push({ emoji: '🍞', color: '#e8a838', width: 80 });

  // Sauces
  for (const sauce of builder.sauces) {
    layers.push({ emoji: TOPPING_ICONS[sauce] || '💧', color: '#f5deb3', width: 70 });
  }

  // Toppings (reversed so first added is closest to patty)
  for (const topping of [...builder.toppings].reverse()) {
    layers.push({ emoji: TOPPING_ICONS[topping] || '•', color: getLayerColor(topping), width: 75 });
  }

  // Patty
  if (builder.patty && builder.patty !== 'null') {
    layers.push({ emoji: TOPPING_ICONS[builder.patty] || '🥩', color: '#6b3a1f', width: 82 });
  }

  // Bottom bun
  layers.push({ emoji: '🍞', color: '#e8a838', width: 85 });

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      gap: 3, padding: '20px 0 8px',
    }}>
      {layers.map((layer, i) => (
        <div
          key={i}
          style={{
            width: `${layer.width}%`,
            height: 28,
            background: `linear-gradient(135deg, ${layer.color}, ${adjustColor(layer.color, -20)})`,
            borderRadius: 14,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.1em',
            boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
            transition: 'all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
          }}
        >
          {layer.emoji}
        </div>
      ))}
    </div>
  );
}

function IngredientRow({ icon, label, price, tag }: { icon: string; label: string; price?: number; tag?: string }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 12px', marginBottom: 6,
      background: '#fafafa', borderRadius: 10,
      border: '1px solid #f0f0f0',
    }}>
      <span style={{ fontSize: '1.2em', width: 28, textAlign: 'center' }}>{icon}</span>
      <span style={{ flex: 1, fontSize: '0.9em', color: '#444', textTransform: 'capitalize' }}>{label}</span>
      {price ? (
        <span style={{
          fontSize: '0.75em', fontWeight: 700, color: '#e67e22',
          background: '#fef3e2', padding: '2px 8px', borderRadius: 8,
        }}>
          +{formatPrice(price)}
        </span>
      ) : tag ? (
        <span style={{
          fontSize: '0.7em', fontWeight: 600, color: '#27ae60',
          background: '#e8f8f0', padding: '2px 8px', borderRadius: 8, textTransform: 'uppercase',
        }}>
          {tag}
        </span>
      ) : null}
    </div>
  );
}

function getLayerColor(topping: string): string {
  if (topping.includes('cheese')) return '#f5c518';
  if (topping === 'bacon') return '#a0522d';
  if (topping === 'avocado') return '#4caf50';
  if (topping === 'fried egg') return '#fff3cd';
  if (topping === 'lettuce') return '#66bb6a';
  if (topping === 'tomato') return '#ef5350';
  if (topping === 'onion') return '#ce93d8';
  if (topping === 'pickles') return '#8bc34a';
  if (topping === 'jalapeños') return '#43a047';
  if (topping === 'mushrooms') return '#bcaaa4';
  return '#e0e0e0';
}

function adjustColor(hex: string, amount: number): string {
  const num = parseInt(hex.replace('#', ''), 16);
  const r = Math.min(255, Math.max(0, ((num >> 16) & 0xff) + amount));
  const g = Math.min(255, Math.max(0, ((num >> 8) & 0xff) + amount));
  const b = Math.min(255, Math.max(0, (num & 0xff) + amount));
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}
