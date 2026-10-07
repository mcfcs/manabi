import { useEffect, useId, useState } from "react";

type Mermaid = typeof import("mermaid").default;
let loader: Promise<Mermaid> | null = null;

/** Mermaid is ~1 MB: loaded the first time a diagram is shown, never before. */
function loadMermaid(): Promise<Mermaid> {
  if (!loader) {
    loader = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        securityLevel: "strict", // labels are model-written: no HTML, no clicks
        theme: "neutral",
        fontFamily: "Public Sans Variable, system-ui, sans-serif",
        flowchart: { htmlLabels: false },
      });
      return m.default;
    });
  }
  return loader;
}

/** Renders one Mermaid diagram to SVG. A diagram that fails to parse reports
 * the error (so the caller can ask the model to repair it) instead of
 * showing broken output. */
export function MermaidDiagram({
  code,
  onError,
}: {
  code: string;
  onError?: (message: string) => void;
}) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setSvg(null);
    setError(null);
    loadMermaid()
      .then(async (m) => {
        await m.parse(code);
        const out = await m.render(`mmd-${id}-${Date.now()}`, code);
        if (!cancelled) setSvg(out.svg);
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        if (!cancelled) {
          setError(msg);
          onError?.(msg);
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  if (error) return null;
  if (!svg) return <div className="sec-diagram-loading" aria-hidden />;
  // Mermaid's own sanitised SVG output (securityLevel strict).
  return <div className="sec-diagram-svg" dangerouslySetInnerHTML={{ __html: svg }} />;
}
