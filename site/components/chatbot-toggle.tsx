'use client';

import { useState } from 'react';
import { chatbotConfig } from '@/lib/chatbot-config';
import { ChatbotPanel } from '@/components/chatbot-panel';

export function ChatbotToggle() {
  const [open, setOpen] = useState(false);

  if (!chatbotConfig.enabled) return null;

  return (
    <div className="deepdoc-chatbot-shell">
      {open ? <ChatbotPanel onClose={() => setOpen(false)} /> : null}
      <button
        aria-expanded={open}
        className="deepdoc-chatbot-toggle"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span aria-hidden="true" className="deepdoc-chatbot-toggle__icon" />
        <span className="deepdoc-chatbot-toggle__label">
          <strong>Ask the codebase</strong>
          <span>Grounded answers with code citations</span>
        </span>
      </button>
    </div>
  );
}
