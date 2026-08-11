import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import {
  BookMarked,
  GraduationCap,
  Lightbulb,
  Loader2,
  MessageSquarePlus,
  SendHorizontal,
  Trash2,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import {
  api,
  ApiError,
  type ChatMessageOut,
  type ChatThreadOut,
  type DocumentOut,
  type NoteListItem,
} from "../../lib/api";
import {
  AiOfflineBanner,
  useAiOnline,
  useCancelJob,
  useChatVoice,
  useGenerationJob,
} from "../ai/common";
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

/** Per-thread material scope: which documents and note sections ground the
 * answers. null scope = everything; explicit arrays narrow it. */
function SourcesPicker({
  moduleId,
  thread,
}: {
  moduleId: string;
  thread: ChatThreadOut;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const documents = useQuery({
    queryKey: ["documents", moduleId],
    queryFn: () => api.get<DocumentOut[]>(`/api/modules/${moduleId}/documents`),
    enabled: open,
  });
  const notes = useQuery({
    queryKey: ["notes", moduleId],
    queryFn: () => api.get<NoteListItem[]>(`/api/modules/${moduleId}/notes`),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const patchScope = useMutation({
    mutationFn: (scope: {
      scope_document_ids: number[] | null;
      scope_note_ids: number[] | null;
    }) => api.patch<ChatThreadOut>(`/api/chat/threads/${thread.id}`, scope),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] }),
  });

  const docIds = (documents.data ?? [])
    .filter((d) => d.ai_included)
    .map((d) => d.id);
  const noteIds = (notes.data ?? []).map((n) => n.id);
  const isAll = thread.scope_document_ids === null && thread.scope_note_ids === null;
  const docsSel = new Set(thread.scope_document_ids ?? docIds);
  const notesSel = new Set(thread.scope_note_ids ?? noteIds);

  function toggle(kind: "doc" | "note", id: number) {
    const nextDocs = new Set(docsSel);
    const nextNotes = new Set(notesSel);
    const set = kind === "doc" ? nextDocs : nextNotes;
    if (set.has(id)) set.delete(id);
    else set.add(id);
    patchScope.mutate({
      scope_document_ids: [...nextDocs],
      scope_note_ids: [...nextNotes],
    });
  }

  const selectedCount = (thread.scope_document_ids?.length ?? 0) +
    (thread.scope_note_ids?.length ?? 0);

  return (
    <div className="chat-scope" ref={rootRef}>
      <button
        className={`chat-teacher-toggle${!isAll ? " on" : ""}`}
        onClick={() => setOpen((v) => !v)}
        title="Choose which materials ground this conversation"
      >
        <BookMarked size={14} strokeWidth={1.75} />
        Sources: {isAll ? "all materials" : `${selectedCount} selected`}
      </button>
      {open && (
        <div className="chat-scope-pop">
          <label className="chat-scope-row chat-scope-all">
            <input
              type="checkbox"
              checked={isAll}
              onChange={() =>
                isAll
                  ? patchScope.mutate({
                      scope_document_ids: docIds,
                      scope_note_ids: noteIds,
                    })
                  : patchScope.mutate({
                      scope_document_ids: null,
                      scope_note_ids: null,
                    })
              }
            />
            All materials
          </label>
          {(documents.isLoading || notes.isLoading) && (
            <p className="chat-scope-hint">
              <Loader2 size={12} className="spin" /> Loading materials…
            </p>
          )}
          {docIds.length > 0 && <p className="chat-scope-hint">Files</p>}
          {(documents.data ?? [])
            .filter((d) => d.ai_included)
            .map((d) => (
              <label key={d.id} className="chat-scope-row">
                <input
                  type="checkbox"
                  checked={docsSel.has(d.id)}
                  onChange={() => toggle("doc", d.id)}
                />
                <span className="chat-scope-name">{d.filename}</span>
              </label>
            ))}
          {noteIds.length > 0 && <p className="chat-scope-hint">Notes</p>}
          {(notes.data ?? []).map((n) => (
            <label key={n.id} className="chat-scope-row">
              <input
                type="checkbox"
                checked={notesSel.has(n.id)}
                onChange={() => toggle("note", n.id)}
              />
              <span className="chat-scope-name">{n.title}</span>
            </label>
          ))}
        </div>
      )}
    </div>
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
  const [voiceOn, setVoiceOn] = useChatVoice();
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const [pendingSpeakId, setPendingSpeakId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const autoPlayed = useRef<Set<number>>(new Set());
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

  const cancelAnswer = useCancelJob();
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
  const setGrounding = useMutation({
    mutationFn: (v: { id: number; strict_grounding: boolean }) =>
      api.patch(`/api/chat/threads/${v.id}`, { strict_grounding: v.strict_grounding }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["chat-threads", moduleId] }),
  });
  const activeThreadObj = threads.data?.find((t) => t.id === activeThread);

  function playMessage(id: number, audioId?: number | null) {
    const audio = audioRef.current;
    if (!audio) return;
    setSpeakingId(id);
    audio.src = `/api/chat/messages/${id}/audio?v=${audioId ?? Date.now()}`;
    audio.play().catch(() => setSpeakingId(null));
  }

  async function speakMessage(id: number, hasAudio: boolean) {
    if (speakingId === id) {
      audioRef.current?.pause();
      setSpeakingId(null);
      return;
    }
    if (hasAudio) {
      const msg = messages.data?.find((m) => m.id === id);
      playMessage(id, msg?.audio_id);
      return;
    }
    // trigger synthesis, then poll until the clip exists (~5-30s)
    setPendingSpeakId(id);
    try {
      await api.post(`/api/chat/messages/${id}/speak`);
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 2500));
        const head = await fetch(`/api/chat/messages/${id}/audio`, {
          method: "GET",
          credentials: "same-origin",
        });
        if (head.ok) {
          queryClient.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
          playMessage(id);
          break;
        }
      }
    } finally {
      setPendingSpeakId(null);
    }
  }

  // Voice-on: auto-play Steven's newest reply once its clip lands (the
  // worker auto-queues synthesis on teacher-mode threads)
  useEffect(() => {
    if (!voiceOn || !activeThreadObj?.teacher_mode) return;
    const last = [...(messages.data ?? [])]
      .reverse()
      .find((m) => m.role === "assistant");
    if (!last || autoPlayed.current.has(last.id)) return;
    if (last.has_audio) {
      autoPlayed.current.add(last.id);
      playMessage(last.id, last.audio_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.data, voiceOn, activeThreadObj?.teacher_mode]);

  // While a reply's audio is being synthesized in the background, keep
  // refreshing so has_audio flips and the autoplay effect fires
  useEffect(() => {
    if (!voiceOn || !activeThreadObj?.teacher_mode) return;
    const last = [...(messages.data ?? [])]
      .reverse()
      .find((m) => m.role === "assistant");
    if (!last || last.has_audio || autoPlayed.current.has(last.id)) return;
    const t = setInterval(
      () =>
        queryClient.invalidateQueries({ queryKey: ["chat-messages", activeThread] }),
      3000,
    );
    const stop = setTimeout(() => clearInterval(t), 90_000);
    return () => {
      clearInterval(t);
      clearTimeout(stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.data, voiceOn, activeThreadObj?.teacher_mode, activeThread]);

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
          <div className="chat-toggle-row">
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
            <button
              className={`chat-teacher-toggle${!activeThreadObj.strict_grounding ? " on" : ""}`}
              onClick={() =>
                setGrounding.mutate({
                  id: activeThreadObj.id,
                  strict_grounding: !activeThreadObj.strict_grounding,
                })
              }
              title="Material only: answer strictly from the materials. Material + reasoning: let the AI reason about related points the materials don't fully cover."
            >
              <Lightbulb size={14} strokeWidth={1.75} />
              {activeThreadObj.strict_grounding
                ? "Material only"
                : "Material + reasoning"}
            </button>
            <SourcesPicker moduleId={moduleId} thread={activeThreadObj} />
          </div>
        )}
        {activeThreadObj?.teacher_mode && (
          <button
            className={`chat-teacher-toggle${voiceOn ? " on" : ""}`}
            onClick={() => {
              const next = !voiceOn;
              setVoiceOn(next); // persists to localStorage as a per-device override
              if (!next) {
                audioRef.current?.pause();
                setSpeakingId(null);
              }
            }}
            title="Steven reads his replies aloud"
          >
            {voiceOn ? (
              <Volume2 size={14} strokeWidth={1.75} />
            ) : (
              <VolumeX size={14} strokeWidth={1.75} />
            )}
            Voice {voiceOn ? "on" : "off"}
          </button>
        )}
        <audio
          ref={audioRef}
          onEnded={() => setSpeakingId(null)}
          onPause={() => setSpeakingId(null)}
        />

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
                {m.role === "assistant" && activeThreadObj?.teacher_mode && (
                  <button
                    className={`chat-speak${speakingId === m.id ? " speaking" : ""}`}
                    onClick={() => speakMessage(m.id, m.has_audio)}
                    disabled={pendingSpeakId === m.id}
                    title={
                      speakingId === m.id
                        ? "Stop"
                        : m.has_audio
                          ? "Play as Steven"
                          : "Synthesize + play as Steven"
                    }
                  >
                    {pendingSpeakId === m.id ? (
                      <Loader2 size={13} className="spin" />
                    ) : speakingId === m.id ? (
                      <VolumeX size={13} strokeWidth={1.75} />
                    ) : (
                      <Volume2 size={13} strokeWidth={1.75} />
                    )}
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
                      : "reading your materials…"}
                  </p>
                )}
                {answering.job && (
                  <button
                    className="link-btn job-cancel chat-stop"
                    onClick={() => cancelAnswer.mutate(answering.job!.id)}
                    disabled={cancelAnswer.isPending}
                  >
                    <X size={13} strokeWidth={2} /> stop
                  </button>
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
