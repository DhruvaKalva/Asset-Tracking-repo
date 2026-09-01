/**
 * Mira -- the dashboard assistant, reachable from every page.
 *
 * The transcript lives here rather than in a store because the backend is
 * stateless: each turn posts the whole conversation. Keeping it in the
 * component that Layout mounts once means the chat survives navigation between
 * pages without anything having to persist it.
 *
 * The button is hidden entirely when the server reports no API key. An
 * assistant that cannot answer is worse than no assistant, so it does not
 * advertise itself.
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMira, useMiraHealth } from "@/hooks/queries";
import { useAuth } from "@/store/auth";
import type { MiraMessage, MiraToolCall } from "@/lib/types";

/** Openers that show what she is for, drawn from the four things people ask. */
const SUGGESTIONS = [
  "How is the fleet doing right now?",
  "Which assets are overdue?",
  "Where is my idle money going?",
  "What needs servicing this week?",
];

/** Tool name -> what it actually read, in the reader's language. */
const TOOL_LABELS: Record<string, string> = {
  fleet_overview: "fleet overview",
  find_assets: "asset search",
  asset_detail: "asset record",
  list_alerts: "open alerts",
  usage_summary: "utilisation",
  cost_insights: "cost analysis",
  list_sites: "sites",
};

export function Mira() {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<MiraMessage[]>([]);
  const [tools, setTools] = useState<Record<number, MiraToolCall[]>>({});

  const health = useMiraHealth();
  const ask = useMira();
  const user = useAuth((s) => s.user);

  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Pin to the newest message, including while the reply is still pending.
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, ask.isPending, open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!health.data?.configured) return null;

  function send(text: string) {
    const content = text.trim();
    if (!content || ask.isPending) return;

    const next: MiraMessage[] = [...messages, { role: "user", content }];
    setMessages(next);
    setDraft("");
    ask.reset();

    // The reply lands at next.length: the transcript we just posted, plus one.
    const replyIndex = next.length;
    ask.mutate(next, {
      onSuccess: (res) => {
        setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
        // Indexed against the assistant turn it explains.
        setTools((t) => ({ ...t, [replyIndex]: res.tools_used }));
      },
    });
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter breaks the line: the convention every chat uses.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(draft);
    }
  }

  const greeting = user?.name ? user.name.split(" ")[0] : "there";

  return (
    <>
      {open && (
        <div
          role="dialog"
          aria-label="Ask Mira"
          className="mira-panel card fixed bottom-28 right-5 z-50 flex w-[min(23rem,calc(100vw-2.5rem))] flex-col overflow-hidden bg-surface"
          style={{ height: "min(34rem, calc(100vh - 10rem))" }}
        >
          <header className="flex items-center gap-2.5 border-b border-hair px-3.5 py-2.5">
            <span className="mira-orb h-7 w-7 shrink-0 rounded-full" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold leading-none text-ink">Mira</div>
              <div className="mt-1 truncate text-[10px] text-ink-muted">
                Fleet assistant · {health.data.model}
              </div>
            </div>
            {messages.length > 0 && (
              <button
                onClick={() => {
                  setMessages([]);
                  setTools({});
                  ask.reset();
                }}
                className="rounded px-1.5 py-1 text-[11px] text-ink-muted hover:text-ink"
                title="Clear conversation"
              >
                Clear
              </button>
            )}
            <button
              onClick={() => setOpen(false)}
              className="rounded px-1.5 py-1 text-base leading-none text-ink-muted hover:text-ink"
              aria-label="Close"
            >
              ×
            </button>
          </header>

          <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-3.5 py-3">
            {messages.length === 0 ? (
              <div className="space-y-3">
                <p className="text-sm leading-snug text-ink-2">
                  Hello {greeting}. I read this dashboard's live data — assets, rentals, alerts,
                  utilisation and costs. Ask me about the fleet and I'll answer from what's on
                  screen.
                </p>
                <p className="text-[11px] leading-snug text-ink-muted">
                  I only cover this fleet. Anything else and I'll say so.
                </p>
                <div className="space-y-1.5 pt-1">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => send(s)}
                      className="block w-full rounded-lg border border-hair px-2.5 py-1.5 text-left text-xs text-ink-2 transition-colors hover:border-[var(--accent)]/50 hover:text-ink"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) => (
                <Bubble key={i} message={m} tools={tools[i]} onNavigate={() => setOpen(false)} />
              ))
            )}

            {ask.isPending && (
              <div className="flex items-center gap-1.5 px-1 py-1" aria-live="polite">
                {[0, 1, 2].map((d) => (
                  <span
                    key={d}
                    className="mira-dot h-1.5 w-1.5 rounded-full bg-[var(--accent)]"
                    style={{ animationDelay: `${d * 0.16}s` }}
                  />
                ))}
                <span className="ml-1 text-[11px] text-ink-muted">Reading the fleet…</span>
              </div>
            )}

            {ask.isError && (
              <p className="rounded-lg border border-critical/30 bg-critical/10 px-2.5 py-2 text-xs leading-snug text-critical">
                {(ask.error as Error).message}
              </p>
            )}
          </div>

          <div className="border-t border-hair p-2.5">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                rows={2}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Ask about the fleet…"
                className="min-h-[2.5rem] flex-1 resize-none rounded-lg border border-hair bg-raised px-2.5 py-1.5 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-[var(--accent)]"
              />
              <button
                onClick={() => send(draft)}
                disabled={!draft.trim() || ask.isPending}
                className="h-9 shrink-0 rounded-lg bg-[var(--accent)] px-3 text-sm font-medium text-white disabled:opacity-40"
              >
                Send
              </button>
            </div>
          </div>
        </div>
      )}

      {/* The sphere. Aria-expanded because it toggles the panel above it. */}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={open ? "Close Mira" : "Ask Mira"}
        className="group fixed bottom-5 right-5 z-50 grid h-[4.25rem] w-[4.25rem] place-items-center"
      >
        <span
          className="mira-halo pointer-events-none absolute inset-0 rounded-full blur-md"
          aria-hidden
        />
        <span className="mira-orb relative grid h-[4.25rem] w-[4.25rem] place-items-center rounded-full transition-transform duration-200 group-hover:scale-105 group-active:scale-95">
          <span className="mira-label text-[9px] font-semibold uppercase tracking-[0.16em] text-white/90">
            Ask
          </span>
          <span className="mira-label -mt-0.5 text-[15px] font-semibold leading-none tracking-tight text-white">
            Mira
          </span>
        </span>
      </button>
    </>
  );
}

function Bubble({
  message,
  tools,
  onNavigate,
}: {
  message: MiraMessage;
  tools?: MiraToolCall[];
  onNavigate: () => void;
}) {
  const mine = message.role === "user";
  return (
    <div className={mine ? "flex justify-end" : "space-y-1.5"}>
      <div
        className={
          mine
            ? "max-w-[85%] rounded-xl rounded-br-sm bg-[var(--accent)]/15 px-2.5 py-1.5 text-sm leading-snug text-ink"
            : "rounded-xl rounded-bl-sm bg-raised px-2.5 py-2 text-sm leading-relaxed text-ink-2"
        }
      >
        {mine ? message.content : <Linked text={message.content} onNavigate={onNavigate} />}
      </div>

      {/* Provenance: which read-model produced the numbers above. */}
      {!mine && tools && tools.length > 0 && (
        <div className="flex flex-wrap gap-1 pl-1">
          {[...new Set(tools.map((t) => t.name))].map((name) => (
            <span
              key={name}
              className="rounded-full border border-hair px-1.5 py-0.5 text-[10px] text-ink-muted"
            >
              {TOOL_LABELS[name] ?? name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Turns equipment ids in the reply into links to the asset page.
 *
 * Mira is told to name assets by id, so the id is the one token in her answer
 * the reader always wants to act on -- making it dead ends the conversation at
 * "now go find it yourself".
 */
const ASSET_ID = /\b([A-Z]{2,4}\d{3,6})\b/g;

function Linked({ text, onNavigate }: { text: string; onNavigate: () => void }) {
  const out: React.ReactNode[] = [];
  let last = 0;

  for (const match of text.matchAll(ASSET_ID)) {
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    out.push(
      <Link
        key={`${at}-${match[1]}`}
        to={`/assets/${match[1]}`}
        onClick={onNavigate}
        className="font-medium text-[var(--accent)] underline decoration-[var(--accent)]/40 underline-offset-2"
      >
        {match[1]}
      </Link>,
    );
    last = at + match[1].length;
  }
  if (last < text.length) out.push(text.slice(last));

  return <span className="whitespace-pre-wrap">{out}</span>;
}
