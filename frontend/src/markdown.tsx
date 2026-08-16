import { memo } from "react";
import Markdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

/** Minimal shape of the mdast nodes this file walks and builds. */
interface MdastNode {
  type: string;
  value?: string;
  children?: MdastNode[];
  data?: unknown;
}

const MARKER = /\[(\d+)\]/g;

/** Markdown reads `$` as math, so prose like "$1,200 and $3,400" parses as one
 *  formula and the amounts disappear. Currency is a `$` followed by a digit and
 *  a formula almost never opens on one, so escaping exactly that keeps amounts
 *  literal while `$E = mc^2$` still renders. Code spans and fences are skipped:
 *  `echo $1` must stay as written. */
function protectCurrency(markdown: string): string {
  return markdown
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, i) => (i % 2 ? part : part.replace(/(?<![\\$])\$(?=\d)/g, "\\$")))
    .join("");
}

/** Turns the `[n]` markers in the answer into superscript references that name
 *  their source on hover. The backend guarantees `[n]` is `citations[n - 1]`
 *  (see backend/app/citations.py), so this only styles what is already true —
 *  anything out of range is left as plain text rather than invented. */
function citationRefs(citations: string[]) {
  const split = (node: MdastNode): MdastNode[] => {
    const value = node.value ?? "";
    const out: MdastNode[] = [];
    let last = 0;
    for (const match of value.matchAll(MARKER)) {
      const n = Number(match[1]);
      if (n < 1 || n > citations.length) continue;
      if (match.index > last) out.push({ type: "text", value: value.slice(last, match.index) });
      out.push({
        type: "citationRef",
        data: { hName: "sup", hProperties: { className: ["cite-ref"], title: citations[n - 1] } },
        children: [{ type: "text", value: `[${n}]` }],
      });
      last = match.index + match[0].length;
    }
    if (out.length === 0) return [node];
    if (last < value.length) out.push({ type: "text", value: value.slice(last) });
    return out;
  };

  const walk = (node: MdastNode): void => {
    if (!node.children) return;
    node.children = node.children.flatMap((child) => {
      if (child.type === "text") return split(child);
      walk(child);
      return [child];
    });
  };

  return () => walk;
}

interface AnswerProps {
  text: string;
  citations: string[];
}

/** Memoised: the composer's state changes on every keystroke, and re-parsing
 *  every answer in the transcript for each one is wasted work. */
export const AnswerBody = memo(function AnswerBody({ text, citations }: AnswerProps) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm, remarkMath, citationRefs(citations)]}
      rehypePlugins={[rehypeKatex]}
    >
      {protectCurrency(text)}
    </Markdown>
  );
});
