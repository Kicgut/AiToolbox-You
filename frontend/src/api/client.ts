async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detailMessage = '';
    try {
      const body = await response.clone().json();
      const error = body?.detail ?? body;
      detailMessage = typeof error === 'string' ? error : error?.message || error?.code || '';
    } catch {
      // Response body was not JSON (or already consumed); fall back below.
    }
    throw new Error(detailMessage || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  async get<T>(url: string): Promise<T> {
    return parseResponse<T>(await fetch(url));
  },
  async post<T>(url: string, body?: unknown): Promise<T> {
    return parseResponse<T>(await fetch(url, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined
    }));
  },
  async patch<T>(url: string, body: unknown): Promise<T> {
    return parseResponse<T>(await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }));
  }
};
