import { useRef, useState } from "react";
import { ask, uploadDocument } from "./api";

interface Turn {
  role: "user" | "assistant";
  text: string;
  citations?: string[];
  grounded?: boolean;
}

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [docs, setDocs] = useState<string[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  async function onUpload(file: File) {
    setBusy(true);
    try {
      const result = await uploadDocument(file);
      setDocs((d) => [...d, `${file.name} · ${result.chunks} chunks`]);
    } catch (err) {
      setDocs((d) => [...d, `${file.name} · upload failed`]);
    } finally {
      setBusy(false);
    }
  }

  async function onAsk() {
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    setTurns((t) => [...t, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = await ask(q);
      setTurns((t) => [
        ...t,
        { role: "assistant", text: res.answer, citations: res.citations, grounded: res.grounded },
      ]);
    } catch (err) {
      setTurns((t) => [...t, { role: "assistant", text: "Request failed. Is the API running?" }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <h1 className="wordmark">docchat</h1>
        <button
          className="upload"
          onClick={() => fileInput.current?.click()}
          disabled={busy}
        >
          Upload document
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.txt,.md"
          hidden
          onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
        />
        <ul className="doclist">
          {docs.length === 0 && <li className="empty">No documents yet. Upload one to start.</li>}
          {docs.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      </aside>

      <main className="chat">
        <div className="turns">
          {turns.length === 0 && (
            <p className="empty">Ask a question about your uploaded documents.</p>
          )}
          {turns.map((turn, i) => (
            <div key={i} className={`turn ${turn.role}`}>
              <p>{turn.text}</p>
              {turn.citations && turn.citations.length > 0 && (
                <div className="citations">
                  {turn.citations.map((c, j) => (
                    <span key={j} className="cite">
                      [{j + 1}] {c}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {busy && <p className="empty">Working…</p>}
        </div>
        <div className="composer">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAsk()}
            placeholder="Ask about your documents"
            disabled={busy}
          />
          <button onClick={onAsk} disabled={busy || !question.trim()}>
            Ask
          </button>
        </div>
      </main>
    </div>
  );
}
