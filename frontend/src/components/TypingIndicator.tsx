export function TypingIndicator() {
  return (
    <div className="flex justify-start mb-4 animate-[fadeIn_0.25s_ease]">
      <div className="flex items-center gap-3 rounded-2xl rounded-bl-md border border-slate-700/60 bg-slate-800/90 px-4 py-3 shadow-lg">
        <div className="flex gap-1.5 items-center" aria-hidden>
          <span className="h-2 w-2 rounded-full bg-clinic-400 animate-[bounce_1s_ease-in-out_infinite]" />
          <span className="h-2 w-2 rounded-full bg-clinic-400 animate-[bounce_1s_ease-in-out_infinite] [animation-delay:150ms]" />
          <span className="h-2 w-2 rounded-full bg-clinic-400 animate-[bounce_1s_ease-in-out_infinite] [animation-delay:300ms]" />
        </div>
        <span className="text-sm text-slate-400">Assistant is thinking…</span>
      </div>
    </div>
  );
}
