import type { Locale } from "../types/chat";

const AR_LETTERS = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/g;
const LATIN_LETTERS = /[A-Za-z]/g;

function letterCounts(sample: string): { ar: number; la: number } {
  const ar = (sample.match(AR_LETTERS) || []).join("").length;
  const la = (sample.match(LATIN_LETTERS) || []).join("").length;
  return { ar, la };
}

/** Match backend language_util.infer_locale_from_text for TTS voice selection. */
export function inferLocaleFromText(sample: string): Locale {
  const t = (sample || "").trim();
  if (!t) return "en";
  const { ar, la } = letterCounts(t);
  if (ar === 0 && la === 0) return "en";
  if (la >= 5 && ar <= 2) return "en";
  if (la >= 12 && ar < la * 0.25) return "en";
  if (ar >= 3 && la === 0) return "ar";
  if (ar >= 8 && ar >= la * 0.55) return "ar";
  if (la > ar) return "en";
  if (ar > la) return "ar";
  return "en";
}

/** Pick TTS locale from assistant reply text; API locale is fallback only. */
export function localeForTts(replyText: string, apiLocale: Locale, userHint: Locale): Locale {
  const fromReply = inferLocaleFromText(replyText);
  const { ar } = letterCounts(replyText);
  if (ar >= 3) return "ar";
  if (fromReply === "ar" || fromReply === "en") return fromReply;
  return apiLocale || userHint;
}

export function plainTextForTts(markdown: string): string {
  return (markdown || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/^#+\s*/gm, "")
    .replace(/^[-*]\s+/gm, "")
    .replace(/\n-{3,}\n/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

export function apiErrorDetail(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String(d.msg) : String(d)))
      .join(", ");
  }
  return fallback;
}

export function newId(): string {
  return crypto.randomUUID();
}
