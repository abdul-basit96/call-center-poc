import { useCallback, useEffect, useState } from "react";
import { API_BASE, fetchHealth, postChat } from "./api/client";
import { ChatComposer } from "./components/ChatComposer";
import { ConfirmPanel } from "./components/ConfirmPanel";
import { MessageList } from "./components/MessageList";
import { VoiceOverlay } from "./components/VoiceOverlay";
import { useVoiceAssistant } from "./hooks/useVoiceAssistant";
import type { ChatMessage, ChatResponse, Locale, PendingConfirmation } from "./types/chat";
import { newId } from "./utils/text";
import { bookingStageLabel } from "./utils/bookingStage";

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threadId, setThreadId] = useState<string>(() => crypto.randomUUID());
  const [input, setInput] = useState("");
  const [audioMode, setAudioMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [nativeAudioLlm, setNativeAudioLlm] = useState(false);
  const [replyLocale, setReplyLocale] = useState<Locale>("en");
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation>(null);
  const [confirmationSummary, setConfirmationSummary] = useState("");
  const [bookingStage, setBookingStage] = useState<string | null>(null);

  useEffect(() => {
    void fetchHealth().then((h) => {
      setApiOk(h != null && h.status === "ok");
      setNativeAudioLlm(Boolean(h?.native_audio_llm));
    });
  }, []);

  const applyResponse = useCallback((data: ChatResponse) => {
    setThreadId(data.thread_id);
    setReplyLocale(data.reply_locale || "en");
    setPendingConfirmation(data.pending_confirmation);
    setConfirmationSummary(data.confirmation_summary || "");
    setBookingStage(data.booking_stage ?? null);
    return data.response;
  }, []);

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || loading) return;
      setLoading(true);
      setMessages((m) => [...m, { id: newId(), role: "user", content: trimmed }]);
      setInput("");
      try {
        const data = await postChat(trimmed, threadId);
        const reply = applyResponse(data);
        setMessages((m) => [...m, { id: newId(), role: "assistant", content: reply }]);
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e);
        setMessages((m) => [
          ...m,
          { id: newId(), role: "assistant", content: `Sorry, something went wrong: ${err}` },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [applyResponse, loading, threadId],
  );

  const onVoiceUser = useCallback((user: string) => {
    setMessages((m) => [...m, { id: newId(), role: "user", content: user }]);
  }, []);

  const onVoiceTurn = useCallback(
    (_user: string, data: ChatResponse) => {
      const reply = applyResponse(data);
      setMessages((m) => [...m, { id: newId(), role: "assistant", content: reply }]);
    },
    [applyResponse],
  );

  const voice = useVoiceAssistant(
    threadId,
    replyLocale,
    audioMode,
    onVoiceTurn,
    onVoiceUser,
    nativeAudioLlm,
  );

  const exitVoiceMode = () => setAudioMode(false);

  const showTyping = loading || (audioMode && voice.phase === "thinking");

  const handleConfirm = () => {
    if (audioMode) void voice.sendConfirm("Yes, please confirm.");
    else void sendText("Yes, please confirm.");
  };

  const handleCancel = () => {
    if (audioMode) void voice.sendConfirm("No, cancel that.");
    else void sendText("No, cancel that.");
  };

  const clearChat = () => {
    setMessages([]);
    setThreadId(crypto.randomUUID());
    setPendingConfirmation(null);
    setConfirmationSummary("");
    setBookingStage(null);
    setInput("");
  };

  const stageHint = bookingStageLabel(bookingStage, replyLocale);

  const pending = Boolean(pendingConfirmation);

  return (
    <div className="flex h-full flex-col max-w-3xl mx-auto w-full">
      <header
        className={`shrink-0 px-4 pt-5 pb-3 transition ${audioMode ? "opacity-50 blur-[2px]" : ""}`}
      >
        <h1 className="text-xl font-bold tracking-tight text-white sm:text-2xl">
          🏥 Medical Appointment Assistant
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Doctors, availability & booking — Arabic or English
        </p>
        {stageHint && !pending && (
          <p className="mt-2 text-xs font-medium text-clinic-400/90">{stageHint}</p>
        )}
        {apiOk === false && (
          <p className="mt-2 text-xs text-amber-400">
            API unreachable at {API_BASE}. Start backend:{" "}
            <code className="text-amber-200">uv run python -m backend.main</code>
          </p>
        )}
      </header>

      <MessageList messages={messages} blurred={audioMode} isThinking={showTyping} />

      {pending && confirmationSummary && (
        <ConfirmPanel
          summary={confirmationSummary}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
          disabled={loading || voice.phase === "thinking" || voice.phase === "speaking"}
          blurred={audioMode}
        />
      )}

      {audioMode && (
        <VoiceOverlay
          phase={voice.phase}
          status={voice.status}
          hint={voice.hint}
          interim={voice.interim}
          error={voice.error}
          pendingConfirmation={pending}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
          onExit={exitVoiceMode}
        />
      )}

      <ChatComposer
        value={input}
        onChange={setInput}
        onSend={() => void sendText(input)}
        disabled={loading}
        placeholder={
          pending
            ? "Type yes/no or use Confirm above…"
            : "Message in Arabic or English…"
        }
        audioMode={audioMode}
        onToggleMode={() => (audioMode ? exitVoiceMode() : setAudioMode(true))}
      />

      <footer className="shrink-0 px-4 pb-3 text-center">
        <button
          type="button"
          onClick={clearChat}
          className="text-xs text-slate-500 hover:text-slate-300 transition"
        >
          Clear chat
        </button>
      </footer>
    </div>
  );
}
