import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { GraduationCap, MessageSquarePlus, SendHorizontal, Trash2 } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  api,
  ApiError,
  type ChatMessageOut,
  type ChatThreadOut,
} from "../../lib/api";
import { AiOfflineBanner, useAiOnline, useGenerationJob } from "../ai/common";
import "./chat.css";

function CitePill({ c }: { c: NonNullable<ChatMessageOut["citations"]>[number] }) {
  const pages =
    c.page_end && c.page_end !== c.page_start
      ? `p. ${c.page_start}–${c.page_end}`
      : `p. ${c.page_start}`;
  return (
    <Link
      to="/documents/$documentId"
      params={{ documentId: String(c.document_id) }}
      search={{ page: c.page_start, highlight: c.chunk_id }}
      className="citation-pill"
    >
      {c.document_title} · {pages}
    </Link>
  );
}

export function ChatTab({ moduleId }: { moduleId: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const search = useSearch({ from: "/courses/$courseId/modules/$moduleId" });
  const aiOnline = useAiOnline();
  const [activeThread, setActiveThread] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const askHandled = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const threads = useQuery({
    queryKey: ["chat-threads", moduleId],
    queryFn: () =>
      api.get<ChatThreadOut[]>(`/api/modules/${moduleId}/chat/threads`),
  });

  useEffect(() => {
    if (activeThread == null && threads.data?.length) {
      setActiveThread(threads.data[0].id);
    }
  }, [threads.data, activeThread]);

  // "Ask Steven" deep link from the document viewer: create a teacher-mode
  // thread pre-seeded with the quoted passage.
  useEffect(() => {
    const ask = (search as { ask?: string }).ask;
    if (!ask || askHandled.current) return;
    askHandled.current = true;
    (async () => {
      const t = await api.post<ChatThreadOut>(
        `/api/modules/${moduleId}/chat/threads`,
      );
      await api.patch(`/api/chat/threads/${t.id}`, {
        teacher_mode: true,
        title: "Ask Steven",
      });
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] });
      setActiveThread(t.id);
      const r = await api.post<{ job_id: number }>(
        `/api/chat/threads/${t.id}/messages`,
        { content: ask },
      );
      answering.start(r.job_id);
      navigate({
        to: ".",
        search: (prev: Record<string, unknown>) => ({ ...prev, ask: undefined }),
        replace: true,
      });
    })().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const messages = useQuery({
    queryKey: ["chat-messages", activeThread],
    queryFn: () =>
      api.get<ChatMessageOut[]>(`/api/chat/threads/${activeThread}/messages`),
    enabled: activeThread != null,
  });

  const answering = useGenerationJob(moduleId, "chat_answer", () => {
    queryClient.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
    queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] });
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.data, answering.job?.preview]);

  const newThread = useMutation({
    mutationFn: () =>
      api.post<ChatThreadOut>(`/api/modules/${moduleId}/chat/threads`),
    onSuccess: (t) => {
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] });
      setActiveThread(t.id);
    },
  });

  const removeThread = useMutation({
    mutationFn: (id: number) => api.delete(`/api/chat/threads/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] });
      setActiveThread(null);
    },
  });

  const toggleTeacher = useMutation({
    mutationFn: (v: { id: number; teacher_mode: boolean }) =>
      api.patch(`/api/chat/threads/${v.id}`, { teacher_mode: v.teacher_mode }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] }),
  });
  const activeThreadObj = threads.data?.find((t) => t.id === activeThread);

  const send = useMutation({
    mutationFn: (content: string) =>
      api.post<{ job_id: number }>(`/api/chat/threads/${activeThread}/messages`, {
        content,
      }),
    onSuccess: (r) => {
      setError(null);
      setInput("");
      answering.start(r.job_id);
      queryClient.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to send"),
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    const content = input.trim();
    if (!content || answering.running) return;
    if (activeThread == null) {
      const t = await api.post<ChatThreadOut>(
        `/api/modules/${moduleId}/chat/threads`,
      );
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] });
      setActiveThread(t.id);
      // send into the fresh thread
      const r = await api.post<{ job_id: number }>(
        `/api/chat/threads/${t.id}/messages`,
        { content },
      );
      setInput("");
      answering.start(r.job_id);
      return;
    }
    send.mutate(content);
  }

  return (
    <div className="chat-tab">
      <aside className="chat-threads">
        <button
          className="btn chat-new"
          onClick={() => newThread.mutate()}
          disabled={newThread.isPending}
        >
          <MessageSquarePlus size={15} strokeWidth={1.75} /> New chat
        </button>
        <div className="chat-thread-list">
          {(threads.data ?? []).map((t) => (
            <div
              key={t.id}
              className={`chat-thread-item${t.id === activeThread ? " active" : ""}`}
            >
              <button className="chat-thread-title" onClick={() => setActiveThread(t.id)}>
                {t.title}
              </button>
              <button
                className="icon-btn danger chat-thread-del"
                onClick={() => removeThread.mutate(t.id)}
                aria-label="Delete conversation"
              >
                <Trash2 size={13} strokeWidth={1.5} />
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="chat-main">
        {!aiOnline && <AiOfflineBanner />}

        {activeThreadObj && (
          <button
            className={`chat-teacher-toggle${activeThreadObj.teacher_mode ? " on" : ""}`}
            onClick={() =>
              toggleTeacher.mutate({
                id: activeThreadObj.id,
                teacher_mode: !activeThreadObj.teacher_mode,
              })
            }
            title="Steven mode: answers delivered in character — grounding rules unchanged"
          >
            <GraduationCap size={14} strokeWidth={1.75} />
            Steven mode {activeThreadObj.teacher_mode ? "on" : "off"}
          </button>
        )}

        <div className="chat-messages">
          {(messages.data ?? []).length === 0 && !answering.running && (
            <div className="gen-empty chat-empty">
              <p>
                Ask anything about this module. Answers come strictly from your
                materials with page citations — and if the materials don't cover
                it, I'll say so before answering from general knowledge.
              </p>
            </div>
          )}
          {(messages.data ?? []).map((m) => (
            <div key={m.id} className={`chat-msg ${m.role}`}>
              <div className="chat-bubble">
                {m.general_knowledge && (
                  <span className="badge stale chat-gk-badge">
                    general knowledge — not from your materials
                  </span>
                )}
                <p>{m.content}</p>
                {m.citations && m.citations.length > 0 && (
                  <div className="chat-cites">
                    {m.citations.map((c, i) => (
                      <CitePill key={i} c={c} />
                    ))}
                  </div>
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
                      : "reading your materials…"}
                  </p>
                )}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && <p className="error-text">{error}</p>}
        {answering.job?.status === "failed" && (
          <p className="error-text">Answer failed: {answering.job.error}</p>
        )}

        <form className="chat-input" onSubmit={submit}>
          <input
            className="input"
            placeholder="Ask about this module…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={answering.running}
          />
          <button
            className="btn btn-primary"
            disabled={!input.trim() || answering.running || send.isPending}
            aria-label="Send"
          >
            <SendHorizontal size={16} strokeWidth={1.75} />
          </button>
        </form>
      </section>
    </div>
  );
}
