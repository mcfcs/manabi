import { SendHorizontal } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef } from "react";

/**
 * Shared chat composer (assistant + module chat). Auto-growing textarea so
 * messages can hold line breaks. Send convention:
 *  - Desktop: Enter sends, Shift+Enter inserts a newline.
 *  - Mobile (≤767px): Enter always inserts a newline; send via the button —
 *    on-screen keyboards have no Shift and users need multi-line input.
 * IME composition (e.g. Japanese) is respected — Enter while composing never
 * sends.
 */
export function ChatComposer({
  value,
  onChange,
  onSend,
  disabled = false,
  sending = false,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled?: boolean;
  sending?: boolean;
  placeholder: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  function autogrow(el: HTMLTextAreaElement) {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }
  // collapse back to one row once the parent clears the value after a send
  useEffect(() => {
    if (value === "" && ref.current) ref.current.style.height = "auto";
  }, [value]);

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
    const mobile = window.matchMedia("(max-width: 767px)").matches;
    if (e.shiftKey || mobile) return; // let the newline through
    e.preventDefault();
    onSend();
  }

  return (
    <form
      className="chat-input"
      onSubmit={(e) => {
        e.preventDefault();
        onSend();
      }}
    >
      <textarea
        ref={ref}
        className="input chat-textarea"
        placeholder={placeholder}
        value={value}
        rows={1}
        onChange={(e) => {
          onChange(e.target.value);
          autogrow(e.target);
        }}
        onKeyDown={onKeyDown}
        disabled={disabled}
      />
      <button
        className="btn btn-primary chat-send"
        disabled={!value.trim() || disabled || sending}
        aria-label="Send"
      >
        <SendHorizontal size={16} strokeWidth={1.75} />
      </button>
    </form>
  );
}
