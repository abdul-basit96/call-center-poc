import ReactMarkdown from "react-markdown";

interface Props {
  role: "user" | "assistant";
  content: string;
}

export function MessageBubble({ role, content }: Props) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4 animate-[fadeIn_0.25s_ease]`}>
      <div
        className={`max-w-[88%] rounded-2xl px-4 py-3 text-[0.95rem] leading-relaxed shadow-lg ${
          isUser
            ? "bg-clinic-600 text-white rounded-br-md"
            : "bg-slate-800/90 text-slate-100 border border-slate-700/60 rounded-bl-md"
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{content}</p>
        ) : (
          <div className="prose prose-invert prose-sm max-w-none prose-p:my-1 prose-headings:my-2">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
