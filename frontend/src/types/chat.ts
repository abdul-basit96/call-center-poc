export type Locale = "ar" | "en";

export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
}

export type PendingConfirmation = "book" | "reschedule" | null;

export interface ChatResponse {
  response: string;
  thread_id: string;
  status: string;
  pending_confirmation: PendingConfirmation;
  confirmation_summary: string | null;
  reply_locale: Locale;
  validation_errors?: string[] | null;
  booking_stage?: string | null;
  action_succeeded?: boolean | null;
}

export type VoicePhase = "idle" | "listening" | "thinking" | "speaking";
