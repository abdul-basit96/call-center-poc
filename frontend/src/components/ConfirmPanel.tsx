import ReactMarkdown from "react-markdown";

interface Props {
  summary: string;
  onConfirm: () => void;
  onCancel: () => void;
  disabled?: boolean;
  blurred?: boolean;
}

export function ConfirmPanel({ summary, onConfirm, onCancel, disabled, blurred }: Props) {
  return (
    <div
      className={`mx-4 mb-3 rounded-xl border border-clinic-500/40 bg-clinic-600/10 p-4 transition-all ${
        blurred ? "blur-md opacity-40 pointer-events-none" : ""
      }`}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-clinic-400 mb-2">
        Confirm booking / reschedule
      </p>
      <p className="text-xs text-slate-400 mb-2">
        Nothing is saved until you tap Confirm. Details were checked against clinic rules.
      </p>
      <div className="prose prose-invert prose-sm max-w-none mb-4 text-slate-200">
        <ReactMarkdown>{summary}</ReactMarkdown>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={onConfirm}
          className="flex-1 rounded-lg bg-clinic-600 hover:bg-clinic-500 disabled:opacity-50 py-2.5 font-semibold text-white transition"
        >
          Confirm
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={onCancel}
          className="flex-1 rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50 py-2.5 font-semibold text-slate-200 transition"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
