import type { VoicePhase } from "../types/chat";

interface Props {
  phase: VoicePhase;
  status: string;
  hint: string;
  interim: string;
  error: string | null;
  pendingConfirmation: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onExit: () => void;
}

export function VoiceOverlay({
  phase,
  status,
  hint,
  interim,
  error,
  pendingConfirmation,
  onConfirm,
  onCancel,
  onExit,
}: Props) {
  const orbClass =
    phase === "listening"
      ? "animate-[breathe_1.1s_ease-in-out_infinite]"
      : phase === "thinking"
        ? "animate-[think_1.6s_linear_infinite]"
        : phase === "speaking"
          ? "animate-[speak_0.45s_ease-in-out_infinite_alternate]"
          : "";

  const barsOn = phase === "listening" || phase === "speaking";

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-gradient-to-b from-slate-900/60 via-slate-950/75 to-slate-950/90 backdrop-blur-[2px]">
      <button
        type="button"
        onClick={onExit}
        className="absolute top-4 right-4 z-10 flex items-center gap-2 rounded-full border border-slate-600/80 bg-slate-800/90 px-4 py-2.5 text-sm font-semibold text-slate-200 shadow-lg hover:border-red-500/50 hover:bg-slate-700 hover:text-white transition"
        aria-label="Exit voice mode"
      >
        <span className="text-base leading-none" aria-hidden>
          ✕
        </span>
        End voice call
      </button>

      <div className="relative mb-8 h-40 w-40">
        <span className="absolute -inset-5 rounded-full border-2 border-clinic-400/40 animate-[ring_2.2s_ease-out_infinite]" />
        <span className="absolute -inset-9 rounded-full border-2 border-clinic-400/25 animate-[ring_2.2s_ease-out_0.7s_infinite]" />
        <div
          className={`absolute inset-0 rounded-full bg-gradient-to-br from-teal-300 via-clinic-600 to-blue-800 shadow-[0_0_60px_rgba(20,184,166,0.5)] ${orbClass}`}
        />
        <div
          className={`absolute bottom-6 left-1/2 flex -translate-x-1/2 gap-1 h-7 items-end transition-opacity ${barsOn ? "opacity-100" : "opacity-0"}`}
        >
          {[0, 1, 2, 3, 4].map((i) => (
            <i
              key={i}
              className="block w-1 rounded-sm bg-teal-300 animate-[bar_0.45s_ease-in-out_infinite_alternate]"
              style={{ animationDelay: `${i * 0.08}s`, height: 8 }}
            />
          ))}
        </div>
      </div>

      <p className="text-lg font-semibold text-slate-100 drop-shadow">{status}</p>
      <p className="mt-1 max-w-xs text-center text-sm text-slate-400">{hint}</p>
      {interim && <p className="mt-2 text-sm text-teal-300/90">{interim}</p>}
      {error && <p className="mt-3 max-w-sm text-center text-sm text-red-300">{error}</p>}

      <button
        type="button"
        onClick={onExit}
        className="mt-8 text-sm text-slate-500 hover:text-slate-300 underline-offset-2 hover:underline transition"
      >
        Switch to text chat
      </button>

      {pendingConfirmation && (
        <div className="mt-4 flex gap-3">
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-lg bg-clinic-600 px-5 py-2.5 font-semibold text-white hover:bg-clinic-500"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg bg-slate-600 px-5 py-2.5 font-semibold text-slate-200 hover:bg-slate-500"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
