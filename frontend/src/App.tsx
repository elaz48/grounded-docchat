import { useEffect, useRef, useState } from "react";
import { ask, listDocuments, uploadDocument, type DocumentSummary } from "./api";
import { AnswerBody } from "./markdown";

interface Turn {
  role: "user" | "assistant";
  text: string;
  citations?: string[];
  grounded?: boolean;
  failed?: boolean;
}

/** Uploading is two waits, not one: sending the bytes (measurable) and then
 *  chunking + embedding them server-side (not measurable, and usually longer).
 *  Showing them as one bar that stalls at 100% is the thing to avoid. */
type Upload =
  | { phase: "idle" }
  | { phase: "sending"; filename: string; percent: number }
  | { phase: "indexing"; filename: string }
  | { phase: "failed"; filename: string; message: string; file: File };

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [upload, setUpload] = useState<Upload>({ phase: "idle" });
  const fileInput = useRef<HTMLInputElement>(null);
  const transcript = useRef<HTMLDivElement>(null);

  // The document list lives in Postgres, not in this component: a reload
  // must still show what has been ingested.
  useEffect(() => {
    refreshDocs();
  }, []);

  // Keep the newest turn in view without stealing focus from the composer.
  useEffect(() => {
    transcript.current?.scrollTo({ top: transcript.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, asking]);

  async function refreshDocs() {
    try {
      setDocs(await listDocuments());
      setDocsError(null);
    } catch {
      setDocsError("Could not reach the API. Is the backend running on :8000?");
    }
  }

  async function onUpload(file: File) {
    setUpload({ phase: "sending", filename: file.name, percent: 0 });
    try {
      await uploadDocument(file, (fraction) =>
        setUpload(
          fraction < 1
            ? { phase: "sending", filename: file.name, percent: Math.round(fraction * 100) }
            : { phase: "indexing", filename: file.name },
        ),
      );
      setUpload({ phase: "idle" });
      await refreshDocs();
    } catch (err) {
      setUpload({
        phase: "failed",
        filename: file.name,
        message: err instanceof Error ? err.message : `Could not upload ${file.name}.`,
        file,
      });
    }
  }

  async function onAsk() {
    const q = question.trim();
    if (!q || asking) return;
    setQuestion("");
    setTurns((t) => [...t, { role: "user", text: q }]);
    setAsking(true);
    try {
      const res = await ask(q);
      setTurns((t) => [
        ...t,
        { role: "assistant", text: res.answer, citations: res.citations, grounded: res.grounded },
      ]);
    } catch (err) {
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          failed: true,
          text: err instanceof Error ? err.message : "The request failed.",
        },
      ]);
    } finally {
      setAsking(false);
    }
  }

  const busyUploading = upload.phase === "sending" || upload.phase === "indexing";

  return (
    <div className="shell">
      <aside className="sidebar">
        <h1 className="wordmark">docchat</h1>
        <button className="upload" onClick={() => fileInput.current?.click()} disabled={busyUploading}>
          Upload document
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.txt,.md"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // allow re-picking the same file after a failure
            if (file) onUpload(file);
          }}
        />

        <div className="upload-status" aria-live="polite">
          {upload.phase === "sending" && (
            <>
              <p className="status-line">
                Uploading {upload.filename} <span className="percent">{upload.percent}%</span>
              </p>
              <div
                className="progress"
                role="progressbar"
                aria-valuenow={upload.percent}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div className="progress-bar" style={{ width: `${upload.percent}%` }} />
              </div>
            </>
          )}
          {upload.phase === "indexing" && (
            <>
              <p className="status-line">Indexing {upload.filename}…</p>
              <p className="status-hint">Extracting text, chunking and embedding.</p>
              <div className="progress" role="progressbar" aria-valuetext="Indexing">
                <div className="progress-bar indeterminate" />
              </div>
            </>
          )}
          {upload.phase === "failed" && (
            <div className="alert">
              <p className="status-line">{upload.filename} was not added.</p>
              <p className="alert-detail">{upload.message}</p>
              <button className="link-button" onClick={() => onUpload(upload.file)}>
                Try again
              </button>
            </div>
          )}
        </div>

        <ul className="doclist">
          {docs.map((d) => (
            <li key={d.document_id}>
              <span className="docname">{d.filename}</span>
              <span className="docmeta">
                {d.chunks} chunk{d.chunks === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ul>
        {docsError && <p className="alert-detail">{docsError}</p>}
        {!docsError && docs.length === 0 && upload.phase === "idle" && (
          <p className="empty">No documents yet. Add a PDF, .txt or .md file to ask about it.</p>
        )}
      </aside>

      <main className="chat">
        <div className="turns" ref={transcript}>
          {turns.length === 0 && (
            <p className="empty">
              {docs.length === 0
                ? "Upload a document on the left, then ask a question about it."
                : `Ask a question about your ${docs.length} document${docs.length > 1 ? "s" : ""}. Every claim in the answer carries the source it came from.`}
            </p>
          )}
          {turns.map((turn, i) => (
            <div
              key={i}
              className={[
                "turn",
                turn.role,
                turn.failed ? "failed" : "",
                turn.grounded === false ? "ungrounded" : "",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {turn.role === "assistant" && !turn.failed ? (
                <AnswerBody text={turn.text} citations={turn.citations ?? []} />
              ) : (
                <p>{turn.text}</p>
              )}
              {turn.citations && turn.citations.length > 0 && (
                <div className="citations">
                  {turn.citations.map((source, j) => (
                    <span key={source} className="cite">
                      [{j + 1}] {source}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {asking && (
            <p className="thinking">
              Searching your documents<span className="dots" aria-hidden="true" />
            </p>
          )}
        </div>
        <div className="composer">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAsk()}
            placeholder="Ask about your documents"
            disabled={asking}
          />
          <button onClick={onAsk} disabled={asking || !question.trim()}>
            Ask
          </button>
        </div>
      </main>
    </div>
  );
}
