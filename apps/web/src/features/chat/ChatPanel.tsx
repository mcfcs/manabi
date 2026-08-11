import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Loader2, SendHorizontal, Volume2, VolumeX, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type ChatMessageOut, type ChatThreadOut } from "../../lib/api";
import { useCancelJob, useChatVoice, useGenerationJob } from "../ai/common";
import "./chat.css";

/** A source-anchored chat "discussion" surfaced over the document viewer.
 * Bottom-sheet on mobile, right-side panel on desktop/iPad. Reuses the module
 * chat endpoints, so these threads also appear in the module Chat tab. */
export function ChatPanel({
  moduleId,
  thread,
  onClose,
}: {
  moduleId: string;
  thread: ChatThreadOut;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [voiceOn, setVoiceOn] = useChatVoice();
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoPlayed = useRef<Set<number>>(new Set());
  const cancelAnswer = useCancelJob();

  const messages = useQuery({
    queryKey: ["chat-messages", thread.id],
    queryFn: () => api.get<ChatMessageOut[]>(`/api/chat/threads/${thread.id}/messages`),
  });

  const answering = useGenerationJob(moduleId, "chat_answer", () => {
    queryClient.invalidateQueries({ queryKey: ["chat-messages", thread.id] });
    queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] });
    queryClient.invalidateQueries({ queryKey: ["document-threads"] });
  });

  const send = useMutation({
    mutationFn: (content: string) =>
      api.post<{ job_id: number }>(`/api/chat/threads/${thread.id}/messages`, {
        content,
      }),
    onSuccess: (r) => answering.start(r.job_id),
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.data, answering.job?.preview]);

  const setGrounding = useMutation({
    mutationFn: (strict: boolean) =>
      api.patch(`/api/chat/threads/${thread.id}`, { strict_grounding: strict }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] }),
  });

  function playMessage(id: number, audioId?: number | null) {
    const audio = audioRef.current;
    if (!audio) return;
    setSpeakingId(id);
    audio.src = `/api/chat/messages/${id}/audio?v=${audioId ?? Date.now()}`;
    audio.play().catch(() => setSpeakingId(null));
  }

  // Auto-play Steven's newest reply when voice is on.
  useEffect(() => {
    if (!voiceOn) return;
    const list = messages.data ?? [];
    const last = list[list.length - 1];
    if (
      last &&
      last.role === "assistant" &&
      last.has_audio &&
      !autoPlayed.current.has(last.id)
    ) {
      autoPlayed.current.add(last.id);
      playMessage(last.id, last.audio_id);
    }
  }, [messages.data, voiceOn]);

  // The first message always carries the highlighted passage so retrieval
  // finds it; the user's own question leads, or we default to "explain this".
  const isFirst = (messages.data ?? []).length === 0;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (answering.running) return;
    const q = input.trim();
    if (!q && !isFirst) return;
    let content = q;
    if (isFirst && thread.source_quote) {
      const where = thread.source_page != null ? ` (page ${thread.source_page})` : "";
      content = q
        ? `${q}\n\nRegarding this passage${where}: "${thread.source_quote}"`
        : `Explain what this passage means${where}: "${thread.source_quote}"`;
    }
    if (!content) return;
    setInput("");
    send.mutate(content);
  }

  return (
    <>
      <div className="chat-panel-backdrop" onClick={onClose} />
      <aside className="chat-panel" role="dialog" aria-label="Discussion">
        <header className="chat-panel-head">
          <div className="chat-panel-title">
            <span>Ask</span>
            {thread.source_page != null && (
              <span className="chat-panel-ref">p. {thread.source_page}</span>
            )}
          </div>
          <div className="chat-panel-head-actions">
            <button
              className={`chat-teacher-toggle${voiceOn ? " on" : ""}`}
              onClick={() => {
                const next = !voiceOn;
                setVoiceOn(next);
                if (!next) {
                  audioRef.current?.pause();
                  setSpeakingId(null);
                }
              }}
              title="Steven reads his replies aloud"
            >
              {voiceOn ? (
                <Volume2 size={13} strokeWidth={1.75} />
              ) : (
                <VolumeX size={13} strokeWidth={1.75} />
              )}
              Voice
            </button>
            <button className="icon-btn" onClick={onClose} aria-label="Close">
              <X size={16} strokeWidth={1.75} />
            </button>
          </div>
        </header>

        {thread.source_quote && (
          <blockquote className="chat-panel-quote">"{thread.source_quote}"</blockquote>
        )}

        <button
          className={`chat-teacher-toggle chat-panel-mode${!thread.strict_grounding ? " on" : ""}`}
          onClick={() => setGrounding.mutate(thread.strict_grounding)}
          title="Material only vs. let Steven reason beyond the passage"
        >
          {thread.strict_grounding ? "Material only" : "Material + reasoning"}
        </button>

        <div className="chat-panel-messages">
          {isFirst && !answering.running && (
            <p className="chat-panel-hint">
              Ask anything about this passage — or just hit send and Steven will
              explain it.
            </p>
          )}
          {(messages.data ?? []).map((m) => (
            <div key={m.id} className={`chat-msg ${m.role}`}>
              <div className="chat-bubble">
                {m.general_knowledge && (
                  <span className="badge stale chat-gk-badge">
                    reasoned — not directly from the text
                  </span>
                )}
                <p>{m.content}</p>
                {m.citations && m.citations.length > 0 && (
                  <div className="chat-cites">
                    {m.citations.map((c, i) =>
                      c.document_id == null ? (
                        <span key={i} className="citation-pill removed">
                          source removed
                        </span>
                      ) : (
                        <Link
                          key={i}
                          to="/documents/$documentId"
                          params={{ documentId: String(c.document_id) }}
                          search={{ page: c.page_start ?? 1, highlight: c.chunk_id }}
                          className="citation-pill"
                        >
                          {c.document_title} · p. {c.page_start}
                        </Link>
                      ),
                    )}
                  </div>
                )}
                {m.role === "assistant" && m.has_audio && (
                  <button
                    className={`chat-speak${speakingId === m.id ? " speaking" : ""}`}
                    onClick={() =>
                      speakingId === m.id
                        ? (audioRef.current?.pause(), setSpeakingId(null))
                        : playMessage(m.id, m.audio_id)
                    }
                    title="Play as Steven"
                  >
                    <Volume2 size={13} strokeWidth={1.75} />
                  </button>
                )}
              </div>
            </div>
          ))}
          {answering.running && (
            <div className="chat-msg assistant">
              <div className="chat-bubble chat-typing">
                {answering.job?.preview ? (
                  <p className="chat-preview">{answering.job.preview}</p>
                ) : (
                  <p className="chat-thinking">
                    {answering.job?.status === "queued"
                      ? "waiting for the AI node…"
                      : "thinking…"}
                  </p>
                )}
                {answering.job && (
                  <button
                    className="link-btn job-cancel chat-stop"
                    onClick={() => cancelAnswer.mutate(answering.job!.id)}
                  >
                    <X size={13} strokeWidth={2} /> stop
                  </button>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <audio
          ref={audioRef}
          onEnded={() => setSpeakingId(null)}
          onPause={() => setSpeakingId(null)}
        />

        <form className="chat-input" onSubmit={submit}>
          <input
            className="input"
            placeholder={isFirst ? "Ask about this… (or send to explain)" : "Ask a follow-up…"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={answering.running}
          />
          <button
            className="btn btn-primary"
            disabled={answering.running || (!isFirst && !input.trim())}
            aria-label="Send"
          >
            {answering.running ? (
              <Loader2 size={16} className="spin" />
            ) : (
              <SendHorizontal size={16} strokeWidth={1.75} />
            )}
          </button>
        </form>
      </aside>
    </>
  );
}
