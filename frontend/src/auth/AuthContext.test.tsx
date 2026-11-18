// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider } from './AuthContext';
import { useAuth } from './useAuth';

// Mock aws-amplify/auth
vi.mock('aws-amplify/auth', () => ({
  signIn: vi.fn(),
  signOut: vi.fn(),
  getCurrentUser: vi.fn(),
  fetchAuthSession: vi.fn(),
}));

import {
  signIn as amplifySignIn,
  signOut as amplifySignOut,
  getCurrentUser,
  fetchAuthSession,
} from 'aws-amplify/auth';

const mockSignIn = vi.mocked(amplifySignIn);
const mockSignOut = vi.mocked(amplifySignOut);
const mockGetCurrentUser = vi.mocked(getCurrentUser);
const mockFetchAuthSession = vi.mocked(fetchAuthSession);

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="authenticated">{String(auth.authenticated)}</span>
      <span data-testid="userId">{auth.userId ?? 'null'}</span>
      <span data-testid="loading">{String(auth.loading)}</span>
      <span data-testid="error">{auth.error ?? 'null'}</span>
      <button onClick={() => { auth.signIn('user@test.com', 'pass123').catch(() => {}); }}>
        Sign In
      </button>
      <button onClick={() => void auth.signOut()}>Sign Out</button>
    </div>
  );
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('starts in loading state and resolves to unauthenticated when no session', async () => {
    mockGetCurrentUser.mockRejectedValue(new Error('No user'));

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    expect(screen.getByTestId('authenticated').textContent).toBe('false');
    expect(screen.getByTestId('userId').textContent).toBe('null');
  });

  it('restores existing session on mount', async () => {
    mockGetCurrentUser.mockResolvedValue({
      userId: 'user-123',
      username: 'testuser',
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated').textContent).toBe('true');
    });

    expect(screen.getByTestId('userId').textContent).toBe('user-123');
    expect(screen.getByTestId('loading').textContent).toBe('false');
  });

  it('signIn updates state on success', async () => {
    mockGetCurrentUser
      .mockRejectedValueOnce(new Error('No user'))
      .mockResolvedValue({ userId: 'user-456', username: 'testuser' });
    mockSignIn.mockResolvedValue({
      isSignedIn: true,
      nextStep: { signInStep: 'DONE' },
    });

    const user = userEvent.setup();

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    await user.click(screen.getByText('Sign In'));

    await waitFor(() => {
      expect(screen.getByTestId('authenticated').textContent).toBe('true');
    });

    expect(mockSignIn).toHaveBeenCalledWith({
      username: 'user@test.com',
      password: 'pass123',
    });
    expect(screen.getByTestId('userId').textContent).toBe('user-456');
  });

  it('signIn sets error on failure', async () => {
    mockGetCurrentUser.mockRejectedValue(new Error('No user'));
    const authError = new Error('Incorrect username or password.');
    authError.name = 'NotAuthorizedException';
    mockSignIn.mockRejectedValue(authError);

    const user = userEvent.setup();

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading').textContent).toBe('false');
    });

    await user.click(screen.getByText('Sign In'));

    await waitFor(() => {
      expect(screen.getByTestId('error').textContent).toBe(
        'Incorrect username or password.',
      );
    });
    expect(screen.getByTestId('authenticated').textContent).toBe('false');
  });

  it('signOut clears state', async () => {
    mockGetCurrentUser.mockResolvedValue({
      userId: 'user-789',
      username: 'testuser',
    });
    mockSignOut.mockResolvedValue(undefined);

    const user = userEvent.setup();

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('authenticated').textContent).toBe('true');
    });

    await user.click(screen.getByText('Sign Out'));

    await waitFor(() => {
      expect(screen.getByTestId('authenticated').textContent).toBe('false');
    });
    expect(screen.getByTestId('userId').textContent).toBe('null');
  });

  it('getJwtToken returns token from session', async () => {
    mockGetCurrentUser.mockResolvedValue({
      userId: 'user-1',
      username: 'testuser',
    });
    mockFetchAuthSession.mockResolvedValue({
      tokens: {
        idToken: { toString: () => 'jwt-token-abc' },
      },
    } as ReturnType<typeof fetchAuthSession> extends Promise<infer T> ? T : never);

    let jwtToken = '';

    function TokenConsumer() {
      const auth = useAuth();
      return (
        <button
          onClick={async () => {
            jwtToken = await auth.getJwtToken();
          }}
        >
          Get Token
        </button>
      );
    }

    const user = userEvent.setup();

    render(
      <AuthProvider>
        <TokenConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Get Token')).toBeEnabled();
    });

    await user.click(screen.getByText('Get Token'));

    await waitFor(() => {
      expect(jwtToken).toBe('jwt-token-abc');
    });
  });

  it('getAwsCredentials returns credentials from session', async () => {
    mockGetCurrentUser.mockResolvedValue({
      userId: 'user-1',
      username: 'testuser',
    });
    mockFetchAuthSession.mockResolvedValue({
      credentials: {
        accessKeyId: 'AKIA...',
        secretAccessKey: 'secret',
        sessionToken: 'session-tok',
      },
    } as ReturnType<typeof fetchAuthSession> extends Promise<infer T> ? T : never);

    let creds: { accessKeyId: string; secretAccessKey: string; sessionToken?: string } | null = null;

    function CredsConsumer() {
      const auth = useAuth();
      return (
        <button
          onClick={async () => {
            creds = await auth.getAwsCredentials();
          }}
        >
          Get Creds
        </button>
      );
    }

    const user = userEvent.setup();

    render(
      <AuthProvider>
        <CredsConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText('Get Creds')).toBeEnabled();
    });

    await user.click(screen.getByText('Get Creds'));

    await waitFor(() => {
      expect(creds).toEqual({
        accessKeyId: 'AKIA...',
        secretAccessKey: 'secret',
        sessionToken: 'session-tok',
      });
    });
  });
});

describe('useAuth', () => {
  it('throws when used outside AuthProvider', () => {
    // Suppress console.error for expected error
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});

    function BadConsumer() {
      useAuth();
      return null;
    }

    expect(() => render(<BadConsumer />)).toThrow(
      'useAuth must be used within an AuthProvider',
    );

    spy.mockRestore();
  });
});
