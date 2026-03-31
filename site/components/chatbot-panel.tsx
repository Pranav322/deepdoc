'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { chatbotConfig } from '@/lib/chatbot-config';

type ChatResponse = {
  answer: string;
  code_citations: Array<{
    file_path: string;
    start_line: number;
    end_line: number;
    symbol_names?: string[];
  }>;
  artifact_citations: Array<{
    file_path: string;
    start_line: number;
    end_line: number;
    artifact_type?: string;
  }>;
  doc_links: Array<{
    title: string;
    url: string;
    doc_path: string;
  }>;
  used_chunks: number;
};

export function ChatbotPanel({ onClose }: { onClose: () => void }) {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [response, setResponse] = useState<ChatResponse | null>(null);

  async function ask() {
    if (!question.trim()) return;
    if (!chatbotConfig.apiBaseUrl) {
      setError('Chatbot backend URL is not configured.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${chatbotConfig.apiBaseUrl}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      if (!res.ok) {
        throw new Error(`Request failed with ${res.status}`);
      }
      const data = (await res.json()) as ChatResponse;
      setResponse(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Chatbot unavailable');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="deepdoc-chatbot-panel mb-1 flex max-h-[min(80vh,56rem)] flex-col">
      <div className="deepdoc-chatbot-panel__header flex items-center justify-between border-b border-fd-border px-4 py-3">
        <h2 className="text-sm font-semibold">Ask the codebase</h2>
        <button className="text-sm text-fd-muted-foreground" onClick={onClose} type="button">
          Close
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <textarea
          className="deepdoc-chatbot-panel__input mb-3 min-h-28 w-full rounded-xl px-3 py-2 text-sm"
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Where is auth handled? How is deployment configured?"
          value={question}
        />
        <button
          className="deepdoc-chatbot-panel__button rounded-xl px-3 py-2 text-sm font-medium"
          disabled={loading}
          onClick={ask}
          type="button"
        >
          {loading ? 'Thinking...' : 'Ask'}
        </button>
        {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}
        {response ? (
          <div className="mt-4 space-y-4 text-sm">
            <div>
              <h3 className="deepdoc-chatbot-panel__section-title mb-1 font-semibold">Answer</h3>
              <div className="deepdoc-chatbot-answer prose prose-sm max-w-none dark:prose-invert">
                <ReactMarkdown>{response.answer}</ReactMarkdown>
              </div>
            </div>
            {response.code_citations.length ? (
              <div>
                <h3 className="deepdoc-chatbot-panel__section-title mb-1 font-semibold">Code citations</h3>
                <ul className="deepdoc-chatbot-citation-list space-y-2">
                  {response.code_citations.map((citation) => (
                    <li key={`${citation.file_path}-${citation.start_line}`}>
                      {citation.file_path}:{citation.start_line}-{citation.end_line}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {response.artifact_citations.length ? (
              <div>
                <h3 className="deepdoc-chatbot-panel__section-title mb-1 font-semibold">Artifact citations</h3>
                <ul className="deepdoc-chatbot-citation-list space-y-2">
                  {response.artifact_citations.map((citation) => (
                    <li key={`${citation.file_path}-${citation.start_line}`}>
                      {citation.file_path}:{citation.start_line}-{citation.end_line}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {response.doc_links.length ? (
              <div>
                <h3 className="deepdoc-chatbot-panel__section-title mb-1 font-semibold">Read next</h3>
                <ul className="deepdoc-chatbot-citation-list space-y-2">
                  {response.doc_links.map((link) => (
                    <li key={link.url}>
                      <a className="underline" href={link.url}>
                        {link.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
