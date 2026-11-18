// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { useState, type FormEvent } from 'react';
import { useAuth } from './useAuth';

export function SignInForm() {
  const { signIn, loading, error } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      await signIn(email, password);
    } catch {
      // Error is surfaced via context state
    }
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Sign in">
      <h2>Sign In</h2>

      {error && (
        <div role="alert" style={{ color: 'red', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      <div style={{ marginBottom: '0.75rem' }}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          autoComplete="username"
        />
      </div>

      <div style={{ marginBottom: '0.75rem' }}>
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          disabled={loading}
          autoComplete="current-password"
        />
      </div>

      <button type="submit" disabled={loading}>
        {loading ? 'Signing in…' : 'Sign In'}
      </button>
    </form>
  );
}
