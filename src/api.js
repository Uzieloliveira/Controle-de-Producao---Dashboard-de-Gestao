const API_URL = import.meta.env.VITE_API_URL || "/api";

export async function apiRequest(path, { token, ...options } = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  }).catch((error) => {
    if (error instanceof TypeError) {
      throw new Error(
        `Não foi possível conectar à API (${API_URL}${path}). Verifique se o backend está iniciado e se VITE_API_URL está configurado corretamente.`,
        { cause: error },
      );
    }
    throw error;
  });

  const responseBody = await response.text();
  let payload = null;
  if (responseBody) {
    try {
      payload = JSON.parse(responseBody);
    } catch {
      if (response.ok) {
        throw new Error(`A API retornou uma resposta inválida para ${path}.`);
      }
    }
  }

  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    throw new Error(
      detail || `A API respondeu com HTTP ${response.status} (${response.statusText}) em ${path}.`,
    );
  }
  return payload ?? {};
}
