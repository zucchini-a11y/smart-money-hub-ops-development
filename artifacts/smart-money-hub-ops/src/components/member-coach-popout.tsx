import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  LockKeyhole,
  MessageCircle,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import {
  useSendMemberCoachMessage,
} from '@workspace/api-client-react';
import type { MemberCoachMessage } from '@workspace/api-client-react';
import { VaydaPortrait, type VaydaState } from './member-experience';
import './member-coach-popout.css';

type CoachLine = { role: 'user' | 'assistant'; content: string };

export function MemberCoachPopout({ lessonTitle }: { lessonTitle?: string }) {
  const coach = useSendMemberCoachMessage();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<CoachLine[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [inputFocused, setInputFocused] = useState(false);
  const [disclaimer, setDisclaimer] = useState('');
  const [typingIndex, setTypingIndex] = useState<number | null>(null);
  const [typedLength, setTypedLength] = useState(0);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const wasOpenedRef = useRef(false);
  const assistantBusy = coach.isPending || typingIndex !== null;
  const portraitState: VaydaState = coach.isPending ? 'thinking' : typingIndex !== null ? 'speaking' : inputFocused ? 'listening' : 'idle';

  useEffect(() => {
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [history, typedLength, assistantBusy, open]);

  useEffect(() => {
    if (typingIndex === null) return;
    const line = history[typingIndex];
    if (!line) {
      setTypingIndex(null);
      setTypedLength(0);
      return;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || typedLength >= line.content.length) {
      setTypingIndex(null);
      setTypedLength(0);
      return;
    }
    const step = Math.max(1, Math.ceil(line.content.length / 120));
    const timer = window.setTimeout(() => {
      setTypedLength((current) => Math.min(line.content.length, current + step));
    }, 22);
    return () => window.clearTimeout(timer);
  }, [history, typingIndex, typedLength]);

  useEffect(() => {
    if (!open) {
      if (wasOpenedRef.current) {
        launcherRef.current?.focus();
        wasOpenedRef.current = false;
      }
      return;
    }
    wasOpenedRef.current = true;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    inputRef.current?.focus();
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (!text || assistantBusy) return;
    setError('');
    setDisclaimer('');
    setMessage('');
    setInputFocused(false);
    setTypingIndex(null);
    setTypedLength(0);
    const previous = history.slice(-12) as MemberCoachMessage[];
    setHistory((lines) => [...lines, { role: 'user', content: text }]);
    try {
      const lessonContext = lessonTitle
        ? `The lesson I’m studying is “${lessonTitle}”. Please use it as context if relevant.\n\n`
        : '';
      const coachMessage = lessonContext.length + text.length <= 1200
        ? `${lessonContext}${text}`
        : text;
      const response = await coach.mutateAsync({ data: { message: coachMessage, history: previous } });
      setDisclaimer(response.disclaimer);
      setHistory((lines) => [...lines, { role: 'assistant', content: response.reply }]);
      setTypedLength(0);
      setTypingIndex(history.length + 1);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Vayda could not respond. Try again.');
    }
  }

  function clearChat() {
    setHistory([]);
    setMessage('');
    setError('');
    setDisclaimer('');
    setInputFocused(false);
    setTypingIndex(null);
    setTypedLength(0);
  }

  return (
    <aside className={`ml-coach-dock${open ? ' is-open' : ''}`} data-testid="academy-coach-popout">
      {open && (
        <section id="academy-vayda-panel" className="ml-coach-popout" role="dialog" aria-modal="false" aria-labelledby="ml-coach-title">
          <header className="ml-coach-popout-head">
            <VaydaPortrait state={portraitState} compact />
            <div className="ml-coach-popout-heading">
              <strong id="ml-coach-title">VAYDA Coach</strong>
              <span>{assistantBusy ? 'Thinking…' : 'Here while you learn'}</span>
            </div>
            {history.length > 0 && (
              <button className="ml-coach-icon-button" type="button" onClick={clearChat} disabled={assistantBusy} aria-label="Clear this temporary chat" title="Clear chat">
                <Trash2 size={15} />
              </button>
            )}
            <button className="ml-coach-icon-button" type="button" onClick={() => setOpen(false)} aria-label="Close Vayda Coach">
              <X size={17} />
            </button>
          </header>

          {lessonTitle && <div className="ml-coach-lesson-context"><span>ACADEMY LESSON</span><strong>{lessonTitle}</strong></div>}

          <div className="ml-coach-thread" ref={threadRef} aria-label="Coach conversation" aria-live="polite">
            {history.length === 0 && (
              <div className="ml-coach-welcome">
                <span>VAYDA</span>
                <p>Ask me to explain a concept or help you think through what you’re studying. I can teach and reflect with you—not tell you when to trade.</p>
              </div>
            )}
            {history.map((line, index) => {
              const isTyping = typingIndex === index;
              const visibleText = isTyping ? line.content.slice(0, typedLength) : line.content;
              return <article className={`ml-coach-line is-${line.role}`} key={`${line.role}-${index}`} data-testid={`academy-coach-message-${index}`}>
                {line.role === 'assistant' && <VaydaPortrait state={isTyping ? 'speaking' : 'idle'} compact />}
                <p>{visibleText}{isTyping && <span className="ml-coach-caret" aria-hidden="true" />}</p>
              </article>;
            })}
            {coach.isPending && (
              <div className="ml-coach-typing" role="status" aria-label="VAYDA is typing">
                <VaydaPortrait state="thinking" compact />
                <span>VAYDA is typing<i /><i /><i /></span>
              </div>
            )}
          </div>

          {disclaimer && <p className="ml-coach-disclaimer" role="note">{disclaimer}</p>}
          {error && <p className="ml-coach-error" role="alert">{error}</p>}

          <form className="ml-coach-form" onSubmit={(event) => void send(event)}>
            <label className="ml-coach-sr-only" htmlFor="academy-coach-message">Ask Vayda about your lesson</label>
            <textarea
              id="academy-coach-message"
              ref={inputRef}
              value={message}
              onChange={(event) => setMessage(event.currentTarget.value)}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              rows={2}
              maxLength={1200}
              placeholder="Ask about this lesson…"
              required
              disabled={assistantBusy}
              data-testid="input-academy-coach-message"
            />
            <button type="submit" disabled={assistantBusy || !message.trim()} aria-label="Send to Vayda" data-testid="button-send-academy-coach">
              <Send size={16} />
            </button>
          </form>
          <footer className="ml-coach-popout-foot">
            <span><LockKeyhole size={12} /> Temporary chat · free-tier messages may be processed by Google. Avoid account details.</span>
            <span>Education only · not financial advice</span>
          </footer>
        </section>
      )}
      <button
        ref={launcherRef}
        className="ml-coach-launcher"
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="academy-vayda-panel"
        aria-label={open ? 'Close Vayda Coach' : 'Open Vayda Coach while learning'}
        data-testid="button-open-academy-coach"
      >
        <span className="ml-coach-launcher-avatar"><VaydaPortrait state={portraitState} compact /></span>
        <span><strong>Ask Vayda</strong><small>{open ? 'Coach is open' : 'While you learn'}</small></span>
        <MessageCircle size={17} />
      </button>
    </aside>
  );
}
