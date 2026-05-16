import { useEffect, useRef } from "react";
import type { ChatMessage } from "../types/chat";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";

interface Props {
  messages: ChatMessage[];
  blurred?: boolean;
  isThinking?: boolean;
}

export function MessageList({ messages, blurred, isThinking }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  return (
    <div
      className={`chat-scroll flex-1 overflow-y-auto px-4 py-4 transition-all duration-300 ${
        blurred ? "blur-md opacity-40 pointer-events-none select-none scale-[0.99]" : ""
      }`}
    >
      {messages.length === 0 && (
        <p className="text-center text-slate-500 text-sm mt-8">
          Ask about doctors, availability, or booking — in Arabic or English.
        </p>
      )}
      {messages.map((m) => (
        <MessageBubble key={m.id} role={m.role} content={m.content} />
      ))}
      {isThinking && <TypingIndicator />}
      <div ref={endRef} />
    </div>
  );
}
