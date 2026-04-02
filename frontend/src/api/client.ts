/** 统一的 API 基础 URL，来自环境变量 */
export const BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

async function extractApiErrorMessage(response: Response, path: string): Promise<string> {
  try {
    const contentType = response.headers.get('content-type') || '';

    if (contentType.includes('application/json')) {
      const payload = await response.json();

      if (typeof payload?.detail === 'string' && payload.detail.trim()) {
        return payload.detail;
      }

      if (typeof payload?.message === 'string' && payload.message.trim()) {
        return payload.message;
      }
    } else {
      const text = await response.text();
      if (text.trim()) {
        return text;
      }
    }
  } catch {
    // Fall back to the generic error message below.
  }

  return `API error ${response.status}: ${path}`;
}

/**
 * 通用 fetch 封装：自动拼接 baseUrl，HTTP 异常时统一抛出错误。
 * @param path  API 路径（以 / 开头）
 */
export async function apiFetch<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(await extractApiErrorMessage(response, path));
  }
  return response.json() as Promise<T>;
}

/**
 * 返回原始 Response，用于需要自行处理特定状态码（如 422）的场景。
 */
export async function apiFetchRaw(path: string): Promise<Response> {
  return fetch(`${BASE_URL}${path}`);
}
