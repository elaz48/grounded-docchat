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

function asObject(text: string): Record<string, unknown> {
  try {
    const body: unknown = JSON.parse(text);
    return typeof body === "object" && body !== null ? (body as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

/** The API explains its failures (e.g. a scanned PDF with no text layer);
 *  pass that message through instead of a bare status code. */
function detail(body: Record<string, unknown>, fallback: string): string {
  return typeof body.detail === "string" ? body.detail : fallback;
}

/**
 * Upload one document, reporting how much of it has been sent (0..1).
 *
 * XMLHttpRequest rather than fetch: fetch cannot report request-body progress,
 * and a 10 MB PDF over a slow link is the one place in this app where a
 * progress bar is information rather than decoration. `onProgress(1)` means the
 * bytes have landed and the server is still chunking and embedding them, which
 * is the slower half of the wait — the caller shows that as its own phase.
 */
export function uploadDocument(
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/documents");

    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    request.upload.onload = () => onProgress?.(1);

    request.onload = () => {
      const body = asObject(request.responseText);
      if (request.status >= 200 && request.status < 300) {
        resolve({
          document_id: String(body.document_id ?? ""),
          filename: file.name,
          chunks: Number(body.chunks ?? 0),
        });
      } else {
        reject(new Error(detail(body, `Upload failed (${request.status})`)));
      }
    };
    request.onerror = () => reject(new Error(`Could not reach the API to upload ${file.name}.`));
    request.onabort = () => reject(new Error(`Upload of ${file.name} was cancelled.`));

    request.send(form);
  });
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
  if (!res.ok) {
    throw new Error(detail(asObject(await res.text()), `The API returned ${res.status}.`));
  }
  return res.json();
}
