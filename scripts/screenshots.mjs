/**
 * README screenshots, captured from the running app.
 *
 *   docker compose up -d           # api + db on :8000
 *   cd frontend && npm run dev     # UI on :5173
 *   node scripts/screenshots.mjs   # -> docs/screenshots/*.png
 *
 * These are real questions against the real API, so each shot costs a couple
 * of cents and takes as long as an answer takes. Nothing here sleeps: every
 * wait is for the element that proves the thing being photographed arrived —
 * rendered KaTeX, a citation chip, the refusal. A timeout means the app is
 * broken, which is the point.
 *
 * One-time setup: npx playwright install chromium
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// playwright is a devDependency of the frontend, which is where every other
// npm dependency in this repo lives; this file sits outside that package.
const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const { chromium } = require(resolve(here, "../frontend/node_modules/playwright"));

const APP = process.env.DOCCHAT_URL ?? "http://localhost:5173";
const OUT = resolve(here, "../docs/screenshots");
const VIEWPORT = { width: 1440, height: 900 };
const ANSWER_TIMEOUT = 120_000; // a cold retrieval + generation round trip

const SHOTS = [
  {
    file: "answer-with-citations.png",
    question: "What is multi-head attention?",
    // The headline shot: markdown, a rendered formula, and the chips that
    // carry the sources.
    expect: [".turn.assistant .katex", ".turn.assistant .cite-ref", ".citations .cite"],
  },
  {
    file: "multi-document.png",
    question: "What does BERT stand for?",
    expect: [".citations .cite"],
  },
  {
    file: "refusal.png",
    question: "Who won the 2022 World Cup?",
    // The guardrail: out-of-corpus questions are refused, not answered.
    expect: [".turn.assistant.ungrounded"],
    refuse: true,
  },
];

/** Ask one question and wait for the answer itself, never for a duration. */
async function ask(page, { question, expect, refuse }) {
  const composer = page.getByPlaceholder("Ask about your documents");
  await composer.fill(question);
  await composer.press("Enter");

  // The transcript starts empty on every load, so the first assistant turn
  // is this question's answer.
  const answer = page.locator(".turn.assistant").first();
  await answer.waitFor({ timeout: ANSWER_TIMEOUT });

  if (await page.locator(".turn.assistant.failed").count()) {
    const reason = await page.locator(".turn.assistant.failed p").innerText();
    throw new Error(`the API did not answer ${JSON.stringify(question)}: ${reason}`);
  }
  for (const selector of expect) {
    await page.locator(selector).first().waitFor({ timeout: 15_000 });
  }
  if (refuse && (await page.locator(".citations .cite").count())) {
    throw new Error(`expected a refusal for ${JSON.stringify(question)}, got citations`);
  }
  // KaTeX swaps in its own fonts; capturing before they load photographs the
  // fallback glyphs at the wrong width.
  await page.evaluate(() => document.fonts.ready);
}

/**
 * Frame the exchange: show question and answer together when they fit, and
 * otherwise keep the end of the answer — where the citation chips are — in
 * view. The app scrolls smoothly, which a screenshot would catch mid-flight.
 */
async function frame(page) {
  await page.evaluate(() => {
    const turns = document.querySelector(".turns");
    const answer = document.querySelector(".turn.assistant");
    const question = answer.previousElementSibling ?? answer;
    turns.style.scrollBehavior = "auto";

    const offset = (el) =>
      el.getBoundingClientRect().top - turns.getBoundingClientRect().top + turns.scrollTop;
    const start = offset(question);
    const end = offset(answer) + answer.offsetHeight;
    const margin = 24;

    turns.scrollTop =
      end - start <= turns.clientHeight - margin
        ? start - margin
        : end - turns.clientHeight + margin;
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2, // legible in a README on a retina screen
  });
  const written = [];

  try {
    for (const shot of SHOTS) {
      const page = await context.newPage();
      // A fresh load per shot: one exchange in the transcript, and the
      // document list is re-fetched, so shot 2 shows what the API really has.
      await page.goto(APP, { waitUntil: "networkidle" });
      await page.locator(".doclist li").first().waitFor({ timeout: 15_000 });
      const documents = await page.locator(".doclist li").count();

      await ask(page, shot);
      await frame(page);

      const path = resolve(OUT, shot.file);
      await page.screenshot({ path, animations: "disabled" });
      written.push(path);
      console.log(`${shot.file}  ${documents} document(s)  ${JSON.stringify(shot.question)}`);
      await page.close();
    }
  } finally {
    await browser.close();
  }

  console.log(`\n${written.length} screenshot(s) in ${OUT}`);
}

await main();
