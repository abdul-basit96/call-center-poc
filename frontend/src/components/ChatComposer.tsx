import type { KeyboardEvent } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
  audioMode: boolean;
  onToggleMode: () => void;
}

export function ChatComposer({
  value,
  onChange,
  onSend,
  disabled,
  placeholder,
  audioMode,
  onToggleMode,
}: Props) {
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !disabled) onSend();
    }
  };

  return (
    <div className="shrink-0 border-t border-slate-800/80 bg-slate-950/95 px-4 py-3 backdrop-blur-md">
      <div className="mx-auto flex max-w-3xl gap-2 items-end">
        <button
          type="button"
          onClick={onToggleMode}
          title={audioMode ? "Switch to text" : "Switch to voice"}
          className="shrink-0 rounded-xl border border-clinic-500/50 bg-clinic-600/20 px-4 py-3 font-semibold text-clinic-300 hover:bg-clinic-600/35 transition min-h-[48px]"
        >
          {audioMode ? "⌨️ Text" : "🎤 Voice"}
        </button>

        {audioMode ? (
          <button
            type="button"
            onClick={onToggleMode}
            className="flex-1 rounded-xl border border-slate-600 bg-slate-800/60 py-3 text-sm font-medium text-slate-300 hover:bg-slate-700 hover:text-white transition min-h-[48px]"
          >
            End voice call — return to text
          </button>
        ) : (
          <>
            <textarea
              value={value}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              rows={1}
              placeholder={placeholder}
              className="flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-3 text-slate-100 placeholder:text-slate-500 focus:border-clinic-500 focus:outline-none focus:ring-1 focus:ring-clinic-500/50 disabled:opacity-50 min-h-[48px] max-h-32"
            />
            <button
              type="button"
              disabled={disabled || !value.trim()}
              onClick={onSend}
              className="shrink-0 rounded-xl bg-clinic-600 px-5 py-3 font-semibold text-white hover:bg-clinic-500 disabled:opacity-40 transition min-h-[48px]"
            >
              Send
            </button>
          </>
        )}
      </div>
    </div>
  );
}
