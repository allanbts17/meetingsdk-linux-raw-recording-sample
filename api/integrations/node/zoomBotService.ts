/* eslint-disable max-len, require-jsdoc, valid-jsdoc */
import {GoogleAuth} from "google-auth-library";

const base = "https://zoom-bot-api-722146628233.us-central1.run.app";
const auth = new GoogleAuth();

export class ZoomBotError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

/** Forward one request; callers retain the same idempotency key on retries. */
export async function zoomBotRequest(
  method: "GET" | "POST" | "DELETE", path: string,
  body?: unknown, key?: string,
): Promise<{status: number; data: unknown}> {
  if (!/^\/v1\/(bots|operations|capacity)(\/|\?|$)/.test(path) ||
      path.includes("..") || path.includes("#")) {
    throw new ZoomBotError(400, "INVALID_ROUTE");
  }
  if (method !== "GET" && !/^[A-Za-z0-9_-]{16,128}$/.test(key || "")) {
    throw new ZoomBotError(400, "INVALID_IDEMPOTENCY_KEY");
  }
  try {
    const client = await auth.getIdTokenClient(base);
    const response = await client.request({
      url: base + path, method, data: body,
      headers: key ? {"Idempotency-Key": key} : {},
      timeout: 25000, retry: false, maxRedirects: 0,
    });
    return {status: response.status, data: response.data};
  } catch (error: unknown) {
    // Google/Gaxios errors contain request bodies and credentials. Never expose them.
    const upstream = error as {response?: {status?: number; data?: {error?: {code?: string}}}};
    const status = upstream.response?.status;
    const code = upstream.response?.data?.error?.code;
    if (status && status >= 400 && status <= 599 && code && /^[A-Z0-9_]{1,80}$/.test(code)) {
      throw new ZoomBotError(status, code);
    }
    throw new ZoomBotError(503, "ZOOM_BOT_UNAVAILABLE");
  }
}
