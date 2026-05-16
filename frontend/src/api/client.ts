import type { ChatResponse, Locale } from "../types/chat";
import { apiErrorDetail } from "../utils/text";

const API_BASE = (import.meta.env.VITE_API_URL || "/api").replace(/\/$/, "");

async function parseJson<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(apiErrorDetail(body, res.statusText || "Request failed"));
  }
  return body as T;
}

export async function postChat(message: string, threadId: string): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId }),
  });
  return parseJson<ChatResponse>(res);
}

export async function postTranscribe(
  blob: Blob,
  hintLocale?: Locale,
): Promise<{ text: string; locale: Locale }> {
  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");
  if (hintLocale) fd.append("hint_locale", hintLocale);
  const res = await fetch(`${API_BASE}/speech/transcribe`, { method: "POST", body: fd });
  return parseJson(res);
}

export async function postSynthesize(text: string, locale: Locale): Promise<Blob> {
  const res = await fetch(`${API_BASE}/speech/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, locale }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(apiErrorDetail(body, "Speech synthesis failed"));
  }
  return res.blob();
}

export async function postChatAudio(
  blob: Blob,
  threadId: string,
  hintLocale?: Locale,
): Promise<ChatResponse> {
  const fd = new FormData();
  fd.append("audio", blob, "recording.webm");
  fd.append("thread_id", threadId);
  if (hintLocale) fd.append("hint_locale", hintLocale);
  const res = await fetch(`${API_BASE}/chat/audio`, { method: "POST", body: fd });
  return parseJson<ChatResponse>(res);
}

export type HealthPayload = {
  status: string;
  speech?: boolean;
  native_audio_llm?: boolean;
};

export async function fetchHealth(): Promise<HealthPayload | null> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) return null;
    return (await res.json()) as HealthPayload;
  } catch {
    return null;
  }
}

export async function checkHealth(): Promise<boolean> {
  const h = await fetchHealth();
  return h != null && h.status === "ok";
}

export { API_BASE };
