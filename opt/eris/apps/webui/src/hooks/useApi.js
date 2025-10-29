import { useCallback } from 'react';
import { useAuth } from '../context/AuthContext.jsx';

function isFormData(body) {
  return typeof FormData !== 'undefined' && body instanceof FormData;
}

export function useApi() {
  const { token, logout } = useAuth();

  const request = useCallback(
    async (path, options = {}) => {
      const headers = new Headers(options.headers || {});
      if (token) {
        headers.set('Authorization', `Bearer ${token}`);
      }

      const body = options.body;
      if (body && !isFormData(body) && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }

      const response = await fetch(path, {
        ...options,
        headers
      });

      if (response.status === 401) {
        logout();
        throw new Error('Authentication required');
      }

      if (response.status === 204) {
        return null;
      }

      const text = await response.text();
      if (!text) {
        return null;
      }
      try {
        return JSON.parse(text);
      } catch (error) {
        return text;
      }
    },
    [token, logout]
  );

  return { request };
}
