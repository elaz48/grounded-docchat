export interface AskResponse {
  answer: string;
  citations: string[];
  grounded: boolean;
}

export interface DocumentSummary {
  document_id: string;
  filename: string;
  chunks: number;
}

/** The API explains upload failures (e.g. a scanned PDF with no text layer);
 *  pass that message through instead of a bare status code. */
async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/documents", { method: "POST", body: form });
  if (!res.ok) throw new Error(await detail(res, `Upload failed (${res.status})`));
  const body = await res.json();
  return { document_id: body.document_id, filename: file.name, chunks: body.chunks };
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch("/api/documents");
  if (!res.ok) throw new Error(`Could not load documents (${res.status})`);
  return (await res.json()).documents;
}

export async function ask(question: string): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) throw new Error(`Ask failed (${res.status})`);
  return res.json();
}
