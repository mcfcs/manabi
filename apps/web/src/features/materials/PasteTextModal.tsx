import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useId, useState } from "react";

import { Modal } from "../../components/Modal";
import { api, type DocumentOut } from "../../lib/api";

export function PasteTextModal({ moduleId, onClose }: {
  moduleId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const id = useId();
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const bytes = new Blob([text]).size;
  const tooLarge = bytes > 2 * 1024 * 1024;
  const save = useMutation({
    mutationFn: () => {
      const name = title.trim().replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/\.txt$/i, "");
      const form = new FormData();
      form.append("file", new File([text], `${name}.txt`, { type: "text/plain" }));
      return api.postForm<DocumentOut>(`/api/modules/${moduleId}/documents`, form);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", moduleId] });
      onClose();
    },
  });

  function close() {
    if (save.isPending) return;
    if ((text || title) && !window.confirm("Discard this unsaved text material?")) return;
    onClose();
  }

  return (
    <Modal title="Add text material" onClose={close} wide>
      <form className="modal-form" onSubmit={(e) => {
        e.preventDefault();
        if (title.trim() && text.trim() && !tooLarge && !save.isPending) save.mutate();
      }}>
        <p className="text-material-hint">
          Paste the whole reading. Once it’s processed, open it to read or listen with Steven.
        </p>
        <div className="text-material-field">
          <label className="field-label" htmlFor={`${id}-title`}>Title</label>
          <input id={`${id}-title`} className="input" value={title} onChange={(e) => setTitle(e.target.value)} required
            maxLength={200} autoFocus disabled={save.isPending}
            placeholder="e.g. Philippine Constitution — Articles VI and VII" />
        </div>
        <div className="text-material-field">
          <label className="field-label" htmlFor={`${id}-text`}>Document text</label>
          <textarea id={`${id}-text`} className="input text-material-input" value={text}
            onChange={(e) => setText(e.target.value)} required rows={12}
            disabled={save.isPending} placeholder="Paste your document here…"
            aria-describedby={`${id}-size`} />
        </div>
        <p id={`${id}-size`} className={tooLarge ? "error-text" : "text-material-hint"}>
          {tooLarge ? "Text exceeds the 2 MB limit." : `${text.trim() ? text.trim().split(/\s+/).length.toLocaleString() : 0} words · Up to 2 MB`}
        </p>
        {save.error && <p className="error-text" role="alert">{save.error.message}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={close} disabled={save.isPending}>Cancel</button>
          <button type="submit" className="btn btn-primary"
            disabled={!title.trim() || !text.trim() || tooLarge || save.isPending}>
            {save.isPending && <Loader2 size={15} className="spin" />}
            {save.isPending ? "Adding…" : "Add material"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
