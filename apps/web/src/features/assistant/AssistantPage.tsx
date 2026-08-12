import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import {
  BookMarked,
  CalendarPlus,
  Check,
  Copy,
  GraduationCap,
  Layers,
  ListTodo,
  Loader2,
  Menu,
  MessageSquarePlus,
  RefreshCw,
  SlidersHorizontal,
  Trash2,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  type AiModelsOut,
  api,
  ApiError,
  type BriefingOut,
  type ChatMessageOut,
  type ChatThreadOut,
  type ThreadAllOut,
} from "../../lib/api";
import {
  AiOfflineBanner,
  useAiOnline,
  useCancelJob,
  useChatVoice,
  useJob,
} from "../ai/common";
import { ChatComposer } from "../chat/ChatComposer";
import "../chat/chat.css";
import "./assistant.css";

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

const actionNoun = (kind: string) => (kind === "create_task" ? "task" : "event");

/** Confirm card for Steven-proposed actions (one or many). Nothing runs until
 * "Add" is tapped; the server re-reads the stored proposals and executes them. */
function ActionCard({ message }: { message: ChatMessageOut }) {
  const qc = useQueryClient();
  const a = message.action!;
  const items = a.items ?? [];
  const run = (verb: "confirm" | "cancel") => ({
    mutationFn: () =>
      api.post(`/api/assistant/messages/${message.id}/action/${verb}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat-messages"] }),
  });
  const confirm = useMutation(run("confirm"));
  const cancel = useMutation(run("cancel"));
  const busy = confirm.isPending || cancel.isPending;

  if (a.status === "done") {
    const results = a.results ?? [];
    const kinds = new Set(items.map((it) => it.kind));
    const noun = kinds.size === 1 ? actionNoun([...kinds][0]) : "item";
    const label =
      results.length === 1
        ? `Added ${noun}: ${results[0]?.title ?? items[0]?.summary}`
        : `Added ${results.length} ${noun}${results.length === 1 ? "" : "s"}`;
    return (
      <div className="action-card done">
        <Check size={14} strokeWidth={2} />
        <span>{label}</span>
      </div>
    );
  }
  if (a.status === "cancelled") {
    return <div className="action-card cancelled">Dismissed.</div>;
  }
  const single = items.length === 1;
  return (
    <div className="action-card">
      <ul className="action-list">
        {items.map((it, i) => {
          const Icon = it.kind === "create_task" ? ListTodo : CalendarPlus;
          return (
            <li key={i} className="action-list-item">
              <Icon size={13} strokeWidth={1.75} />
              <span>{it.summary}</span>
            </li>
          );
        })}
      </ul>
      <div className="action-card-buttons">
        <button
          className="btn btn-primary action-btn"
          onClick={() => confirm.mutate()}
          disabled={busy}
        >
          {confirm.isPending ? (
            <Loader2 size={13} className="spin" />
          ) : single ? (
            `Add ${actionNoun(items[0].kind)}`
          ) : (
            `Add all ${items.length}`
          )}
        </button>
        <button
          className="btn action-btn"
          onClick={() => cancel.mutate()}
          disabled={busy}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Lightweight job tracker (no per-module active-jobs — general jobs aren't
 * module-scoped); tracks a chat_answer job by id until it finishes. */
function useAssistantJob(onDone: () => void) {
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(jobId);
  const running =
    jobId != null &&
    (job.data == null ||
      job.data.status === "queued" ||
      job.data.status === "running");
  useEffect(() => {
    if (jobId != null && job.data?.status === "succeeded") {
      setJobId(null);
      onDone();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.data?.status, jobId]);
  return { start: setJobId, job: job.data, running };
}

interface AssistantModule {
  id: number;
  title: string;
  course_id: number;
  course_code: string;
  accent_color: string | null;
}

/** Cross-module material scope: which modules' materials the assistant may cite. */
function ModuleScopePicker({ thread }: { thread: ChatThreadOut }) {
  const qc = useQueryClient();
  const mods = useQuery({
    queryKey: ["assistant-modules"],
    queryFn: () => api.get<AssistantModule[]>(`/api/assistant/modules`),
  });
  const selected = new Set(thread.scope_module_ids ?? []);
  const patch = useMutation({
    mutationFn: (ids: number[]) =>
      api.patch<ChatThreadOut>(`/api/chat/threads/${thread.id}`, {
        scope_module_ids: ids.length ? ids : null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assistant-threads"] }),
  });
  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    patch.mutate([...next]);
  }
  return (
    <div className="asst-scope">
      <p className="asst-scope-hint">
        Pick modules to always search their materials (otherwise the assistant
        only scans when your question is clearly about them).
      </p>
      {(mods.data ?? []).map((m) => (
        <label key={m.id} className="asst-scope-item">
          <input
            type="checkbox"
            checked={selected.has(m.id)}
            onChange={() => toggle(m.id)}
          />
          <span
            className="asst-scope-dot"
            style={{ background: m.accent_color ?? "var(--accent-blue)" }}
          />
          <span className="asst-scope-code mono">{m.course_code}</span>
          <span className="asst-scope-title">{m.title}</span>
        </label>
      ))}
      {mods.data?.length === 0 && (
        <p className="asst-scope-hint">No modules yet.</p>
      )}
    </div>
  );
}

export function AssistantPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const aiOnline = useAiOnline();
  const [activeThread, setActiveThread] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [voiceOn, setVoiceOn] = useChatVoice();
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const [pendingSpeakId, setPendingSpeakId] = useState<number | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const autoPlayed = useRef<Set<number>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);
  const briefingFired = useRef(false);

  const threads = useQuery({
    queryKey: ["assistant-threads"],
    queryFn: () => api.get<ChatThreadOut[]>(`/api/assistant/threads`),
  });
  const allThreads = useQuery({
    queryKey: ["chat-threads-all"],
    queryFn: () => api.get<ThreadAllOut[]>(`/api/chat/threads/all`),
  });
  const aiModels = useQuery({
    queryKey: ["ai-models"],
    queryFn: () => api.get<AiModelsOut>(`/api/ai/models`),
  });

  useEffect(() => {
    if (activeThread == null && threads.data?.length) {
      setActiveThread(threads.data[0].id);
    }
  }, [threads.data, activeThread]);

  const activeThreadObj = threads.data?.find((t) => t.id === activeThread);

  const messages = useQuery({
    queryKey: ["chat-messages", activeThread],
    queryFn: () =>
      api.get<ChatMessageOut[]>(`/api/chat/threads/${activeThread}/messages`),
    enabled: activeThread != null,
  });

  const cancelAnswer = useCancelJob();
  const answering = useAssistantJob(() => {
    qc.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
    qc.invalidateQueries({ queryKey: ["assistant-threads"] });
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.data, answering.job?.preview]);

  // On open, ensure today's morning briefing exists (generated once per Manila
  // day, cached). Steven's greeting arrives as the first message of the daily
  // thread, so it renders + reads aloud through the existing chat flow.
  const briefing = useMutation({
    mutationFn: () => api.post<BriefingOut>(`/api/assistant/briefing`),
    onSuccess: (b) => {
      setActiveThread(b.thread_id);
      if (b.generating && b.job_id != null) answering.start(b.job_id);
      qc.invalidateQueries({ queryKey: ["assistant-threads"] });
      qc.invalidateQueries({ queryKey: ["chat-threads-all"] });
    },
  });
  useEffect(() => {
    if (briefingFired.current) return;
    briefingFired.current = true;
    briefing.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const newThread = useMutation({
    mutationFn: () => api.post<ChatThreadOut>(`/api/assistant/threads`),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["assistant-threads"] });
      qc.invalidateQueries({ queryKey: ["chat-threads-all"] });
      setActiveThread(t.id);
    },
  });
  const removeThread = useMutation({
    mutationFn: (id: number) => api.delete(`/api/chat/threads/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["assistant-threads"] });
      setActiveThread(null);
    },
  });
  const patchThread = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch<ChatThreadOut>(`/api/chat/threads/${activeThread}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assistant-threads"] }),
  });
  const deleteMsg = useMutation({
    mutationFn: (id: number) => api.delete(`/api/chat/messages/${id}`),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["chat-messages", activeThread] }),
  });
  const regenerate = useMutation({
    mutationFn: (id: number) =>
      api.post<{ job_id: number }>(`/api/chat/messages/${id}/regenerate`),
    onSuccess: (r) => {
      answering.start(r.job_id);
      qc.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Couldn't regenerate"),
  });
  function copyMsg(id: number, text: string) {
    navigator.clipboard?.writeText(text).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId((c) => (c === id ? null : c)), 1200);
    });
  }
  const send = useMutation({
    mutationFn: (content: string) =>
      api.post<{ job_id: number }>(`/api/chat/threads/${activeThread}/messages`, {
        content,
      }),
    onSuccess: (r) => {
      setError(null);
      setInput("");
      answering.start(r.job_id);
      qc.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Failed to send"),
  });

  function doSend() {
    if (activeThread == null) {
      newThread.mutate(); // create then user resends
      return;
    }
    if (input.trim() && !answering.running) send.mutate(input.trim());
  }

  function handleVoice() {
    const next = !voiceOn;
    setVoiceOn(next);
    if (!next) {
      audioRef.current?.pause();
      setSpeakingId(null);
    }
  }
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
      playMessage(id, messages.data?.find((m) => m.id === id)?.audio_id);
      return;
    }
    setPendingSpeakId(id);
    try {
      await api.post(`/api/chat/messages/${id}/speak`);
      for (let i = 0; i < 40; i++) {
        await new Promise((r) => setTimeout(r, 2500));
        const head = await fetch(`/api/chat/messages/${id}/audio`, {
          credentials: "same-origin",
        });
        if (head.ok) {
          qc.invalidateQueries({ queryKey: ["chat-messages", activeThread] });
          playMessage(id);
          break;
        }
      }
    } finally {
      setPendingSpeakId(null);
    }
  }
  // Voice-on: auto-play Steven's newest reply once its clip lands.
  useEffect(() => {
    if (!voiceOn || !activeThreadObj?.teacher_mode) return;
    const last = [...(messages.data ?? [])].reverse().find((m) => m.role === "assistant");
    if (!last || autoPlayed.current.has(last.id)) return;
    if (last.has_audio) {
      autoPlayed.current.add(last.id);
      playMessage(last.id, last.audio_id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.data, voiceOn, activeThreadObj?.teacher_mode]);

  const generalThreads = threads.data ?? [];
  const moduleThreads = (allThreads.data ?? []).filter((t) => !t.is_general);

  return (
    <div className="chat-tab assistant-tab">
      {/* Desktop sidebar */}
      <aside className="chat-threads">
        <button className="btn chat-new" onClick={() => newThread.mutate()}>
          <MessageSquarePlus size={15} strokeWidth={1.75} /> New chat
        </button>
        <ThreadList
          general={generalThreads}
          modules={moduleThreads}
          activeThread={activeThread}
          onSelect={(id) => setActiveThread(id)}
          onDelete={(id) => removeThread.mutate(id)}
          onOpenModule={(t) => {
            if (t.course_id && t.module_id)
              navigate({
                to: "/courses/$courseId/modules/$moduleId",
                params: {
                  courseId: String(t.course_id),
                  moduleId: String(t.module_id),
                },
                search: { tab: "chat" },
              });
          }}
        />
      </aside>

      <section className="chat-main">
        <header className="chat-mbar">
          <button
            className="icon-btn chat-mbar-btn"
            onClick={() => setDrawer(true)}
            aria-label="Conversations"
          >
            <Menu size={18} strokeWidth={1.75} />
          </button>
          <span className="chat-mbar-title">
            {activeThreadObj?.title ?? "Steven AI Starphase"}
          </span>
          <button
            className="icon-btn chat-mbar-btn"
            onClick={() => newThread.mutate()}
            aria-label="New chat"
          >
            <MessageSquarePlus size={17} strokeWidth={1.75} />
          </button>
        </header>

        {!aiOnline && <AiOfflineBanner />}

        <div className="asst-col">
        {activeThreadObj && (
          <button
            className="chat-settings-btn"
            onClick={() => setSettingsOpen(true)}
          >
            <SlidersHorizontal size={13} strokeWidth={1.75} />
            {activeThreadObj.teacher_mode ? "Steven AI Starphase" : "Plain assistant"} ·{" "}
            {activeThreadObj.scope_module_ids?.length
              ? `${activeThreadObj.scope_module_ids.length} modules`
              : activeThreadObj.auto_materials
                ? "auto materials"
                : "personal + general"}
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
              <p className="asst-empty-title">Steven AI Starphase</p>
              <p>
                Your personal assistant. Ask about your schedule, tasks, or any
                of your courses — or anything else, like coding, math, or
                writing. He'll answer in full, in character.
              </p>
            </div>
          )}
          {(messages.data ?? []).map((m) => (
            <div key={m.id} className={`chat-msg ${m.role}`}>
              {m.role === "assistant" && (
                <img className="chat-avatar" src="/steven.jpg" alt="Steven" />
              )}
              <div className="chat-msg-body">
                <div className="chat-bubble">
                  <p>{m.content}</p>
                  {m.action && <ActionCard message={m} />}
                  {m.citations && m.citations.length > 0 && (
                    <div className="chat-cites">
                      {m.citations.map((c, i) => (
                        <CitePill key={i} c={c} />
                      ))}
                    </div>
                  )}
                </div>
                <div className="chat-actions">
                  <button
                    className="chat-act"
                    onClick={() => copyMsg(m.id, m.content)}
                    title="Copy"
                    aria-label="Copy message"
                  >
                    {copiedId === m.id ? (
                      <Check size={14} strokeWidth={2} />
                    ) : (
                      <Copy size={14} strokeWidth={1.75} />
                    )}
                  </button>
                  {m.role === "assistant" && (
                    <button
                      className="chat-act"
                      onClick={() => regenerate.mutate(m.id)}
                      disabled={regenerate.isPending || answering.running}
                      title="Regenerate"
                      aria-label="Regenerate reply"
                    >
                      <RefreshCw
                        size={14}
                        strokeWidth={1.75}
                        className={regenerate.isPending ? "spin" : ""}
                      />
                    </button>
                  )}
                  {m.role === "assistant" && activeThreadObj?.teacher_mode && (
                    <button
                      className={`chat-act${speakingId === m.id ? " on" : ""}`}
                      onClick={() => speakMessage(m.id, m.has_audio)}
                      disabled={pendingSpeakId === m.id}
                      title={speakingId === m.id ? "Stop" : "Play as Steven"}
                      aria-label="Play as Steven"
                    >
                      {pendingSpeakId === m.id ? (
                        <Loader2 size={14} className="spin" />
                      ) : speakingId === m.id ? (
                        <VolumeX size={14} strokeWidth={1.75} />
                      ) : (
                        <Volume2 size={14} strokeWidth={1.75} />
                      )}
                    </button>
                  )}
                  <button
                    className="chat-act chat-act-del"
                    onClick={() => deleteMsg.mutate(m.id)}
                    disabled={deleteMsg.isPending}
                    title="Delete"
                    aria-label="Delete message"
                  >
                    <Trash2 size={14} strokeWidth={1.75} />
                  </button>
                </div>
              </div>
            </div>
          ))}
          {answering.running && (
            <div className="chat-msg assistant">
              <img className="chat-avatar" src="/steven.jpg" alt="Steven" />
              <div className="chat-bubble chat-typing">
                {answering.job?.preview ? (
                  <p className="chat-preview">{answering.job.preview}</p>
                ) : (
                  <p className="chat-thinking">
                    {answering.job?.status === "queued"
                      ? "waiting for the AI node"
                      : "Steven is typing"}
                    <span className="typing-dots" aria-hidden>
                      <span />
                      <span />
                      <span />
                    </span>
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

        <ChatComposer
          value={input}
          onChange={setInput}
          onSend={doSend}
          disabled={answering.running}
          sending={send.isPending}
          placeholder="Ask Steven anything…"
        />
        </div>
      </section>

      {/* Mobile conversation drawer */}
      {drawer &&
        createPortal(
          <>
            <div className="chat-drawer-backdrop" onClick={() => setDrawer(false)} />
            <aside className="chat-drawer" role="dialog" aria-label="Conversations">
              <header className="chat-drawer-head">
                <span>Steven AI Starphase</span>
                <button
                  className="icon-btn"
                  onClick={() => setDrawer(false)}
                  aria-label="Close"
                >
                  <X size={16} strokeWidth={1.75} />
                </button>
              </header>
              <button
                className="btn chat-new"
                onClick={() => {
                  newThread.mutate();
                  setDrawer(false);
                }}
              >
                <MessageSquarePlus size={15} strokeWidth={1.75} /> New chat
              </button>
              <ThreadList
                general={generalThreads}
                modules={moduleThreads}
                activeThread={activeThread}
                onSelect={(id) => {
                  setActiveThread(id);
                  setDrawer(false);
                }}
                onDelete={(id) => removeThread.mutate(id)}
                onOpenModule={(t) => {
                  setDrawer(false);
                  if (t.course_id && t.module_id)
                    navigate({
                      to: "/courses/$courseId/modules/$moduleId",
                      params: {
                        courseId: String(t.course_id),
                        moduleId: String(t.module_id),
                      },
                      search: { tab: "chat" },
                    });
                }}
              />
            </aside>
          </>,
          document.body,
        )}

      {/* Mobile/desktop settings sheet */}
      {settingsOpen &&
        activeThreadObj &&
        createPortal(
          <>
            <div
              className="chat-drawer-backdrop"
              onClick={() => setSettingsOpen(false)}
            />
            <div className="chat-settings-sheet" role="dialog" aria-label="Steven settings">
              <header className="chat-drawer-head">
                <span>Steven's settings</span>
                <button
                  className="icon-btn"
                  onClick={() => setSettingsOpen(false)}
                  aria-label="Close"
                >
                  <X size={16} strokeWidth={1.75} />
                </button>
              </header>
              <div className="chat-settings-body">
                <button
                  className={`chat-teacher-toggle${activeThreadObj.teacher_mode ? " on" : ""}`}
                  onClick={() =>
                    patchThread.mutate({ teacher_mode: !activeThreadObj.teacher_mode })
                  }
                >
                  <GraduationCap size={14} strokeWidth={1.75} />
                  Steven mode {activeThreadObj.teacher_mode ? "on" : "off"}
                </button>
                <button
                  className={`chat-teacher-toggle${activeThreadObj.auto_materials ? " on" : ""}`}
                  onClick={() =>
                    patchThread.mutate({ auto_materials: !activeThreadObj.auto_materials })
                  }
                  title="Search your course materials when a question is clearly about them"
                >
                  <BookMarked size={14} strokeWidth={1.75} />
                  Auto-include materials {activeThreadObj.auto_materials ? "on" : "off"}
                </button>
                {activeThreadObj.teacher_mode && (
                  <button
                    className={`chat-teacher-toggle${voiceOn ? " on" : ""}`}
                    onClick={handleVoice}
                  >
                    {voiceOn ? (
                      <Volume2 size={14} strokeWidth={1.75} />
                    ) : (
                      <VolumeX size={14} strokeWidth={1.75} />
                    )}
                    Voice {voiceOn ? "on" : "off"}
                  </button>
                )}
                <label className="asst-model">
                  <span className="asst-model-label">Model (this chat only)</span>
                  <select
                    className="input asst-model-select"
                    value={activeThreadObj.model_override ?? ""}
                    onChange={(e) =>
                      patchThread.mutate({ model_override: e.target.value || null })
                    }
                  >
                    <option value="">Default</option>
                    {(aiModels.data?.models ?? []).map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="asst-scope-head">Choose materials</div>
                <ModuleScopePicker thread={activeThreadObj} />
              </div>
            </div>
          </>,
          document.body,
        )}
    </div>
  );
}

function ThreadList({
  general,
  modules,
  activeThread,
  onSelect,
  onDelete,
  onOpenModule,
}: {
  general: ChatThreadOut[];
  modules: ThreadAllOut[];
  activeThread: number | null;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onOpenModule: (t: ThreadAllOut) => void;
}) {
  return (
    <div className="chat-thread-list asst-thread-list">
      {general.map((t) => (
        <div
          key={t.id}
          className={`chat-thread-item${t.id === activeThread ? " active" : ""}`}
        >
          <button className="chat-thread-title" onClick={() => onSelect(t.id)}>
            {t.title}
          </button>
          <button
            className="icon-btn danger chat-thread-del"
            onClick={() => onDelete(t.id)}
            aria-label="Delete conversation"
          >
            <Trash2 size={13} strokeWidth={1.5} />
          </button>
        </div>
      ))}
      {modules.length > 0 && (
        <>
          <div className="asst-drawer-section">
            <Layers size={12} strokeWidth={1.75} /> Module chats
          </div>
          {modules.map((t) => (
            <button
              key={t.id}
              className="chat-thread-item asst-module-thread"
              onClick={() => onOpenModule(t)}
            >
              <span className="asst-module-code mono">{t.course_code}</span>
              <span className="chat-thread-title">{t.title}</span>
            </button>
          ))}
        </>
      )}
    </div>
  );
}
