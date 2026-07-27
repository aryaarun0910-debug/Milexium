// Record a guided walkthrough of the Argus command centre.
//
// Not a scroll — a paced tour. Sections that carry the argument get held on
// screen long enough to read; the rest are passed through. The two that earn
// the longest holds are the rejected alternatives (nobody else shows those)
// and the refusals (the product declining to overclaim is the differentiator).
import { chromium } from 'playwright';
import { fileURLToPath } from 'url';
import path from 'path';

const REPO = 'C:/Users/aryaa/Documents/Milexium';
const PAGE = `file:///${REPO}/aletheia/artifacts/command-centre/index.html`;
const OUT = process.argv[2] || `${REPO}/aletheia/artifacts/command-centre/recording`;

// [heading text, seconds to hold]  — held time is reading time, not drama
const TOUR = [
  ['Milexium command centre', 3.5],
  ['How to read this page', 4.0],
  ['Current state', 4.5],
  ['Forecast risk for the upcoming window', 4.0],
  ['Scarce accessible capacity', 4.5],
  ['The decision, and every alternative that was rejected', 8.0],  // the differentiator
  ['What it would cost in future capacity', 5.0],
  ['Uncertainty, and what would invalidate this', 4.5],
  ['Human authorisation', 3.5],
  ['The later actual outcome, against what was expected', 4.5],
  ['What this platform refused to tell you', 9.0],                 // the punchline
  ['Found while wiring the layers together', 5.5],
  ['Every declared input this picture rests on', 4.0],
  ['Limitations', 5.0],
];

const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  recordVideo: { dir: OUT, size: { width: 1600, height: 900 } },
  deviceScaleFactor: 2,           // crisp text in the recording
  reducedMotion: 'no-preference',
});
const page = await context.newPage();
await page.goto(PAGE, { waitUntil: 'networkidle' });
await sleep(1.5);

let found = 0, missed = [];
for (const [heading, hold] of TOUR) {
  // match the heading by its text, tolerant of exact tag/level
  const target = page.getByText(heading, { exact: false }).first();
  try {
    await target.scrollIntoViewIfNeeded({ timeout: 4000 });
    // nudge up so the heading is not jammed against the viewport top
    await page.evaluate(() => window.scrollBy({ top: -60, behavior: 'smooth' }));
    await sleep(0.8);
    found++;
  } catch {
    missed.push(heading);
    continue;
  }
  await sleep(hold);
}

// settle on the closing status line
await page.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }));
await sleep(3.5);

await context.close();   // flushes the video file
await browser.close();

console.log(`sections held: ${found}/${TOUR.length}`);
if (missed.length) console.log('not found: ' + missed.join(' | '));
console.log(`video written under: ${OUT}`);
