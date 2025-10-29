import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

const STORAGE_KEY = 'eris-auth';

const AuthContext = createContext({
  token: null,
  isAuthenticated: false,
  login: async () => {},
  logout: () => {}
});

function loadSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    if (!parsed?.token) {
      return null;
    }
    if (parsed.expiresAt && new Date(parsed.expiresAt) <= new Date()) {
      localStorage.removeItem(STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch (error) {
    console.warn('Failed to load auth session', error);
    return null;
  }
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => loadSession());
  const [error, setError] = useState(null);

  useEffect(() => {
    if (session) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [session]);

  const logout = useCallback(() => {
    setSession(null);
  }, []);

  const login = useCallback(async (password) => {
    setError(null);
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ password })
    });

    if (!response.ok) {
      const message = (await response.text()) || 'Login failed';
      setError(message);
      throw new Error(message);
    }

    const payload = await response.json();
    setSession({
      token: payload.token,
      expiresAt: payload.expires_at || null
    });
  }, []);

  const value = useMemo(
    () => ({
      token: session?.token ?? null,
      isAuthenticated: Boolean(session?.token),
      login,
      logout,
      authError: error,
      clearError: () => setError(null)
    }),
    [session, login, logout, error]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
