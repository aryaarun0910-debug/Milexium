// Record the terminal session: boot, ingest, decide/prove, refuse, then paint
// the architecture. The page types and prints on its own timers — this just
// holds the camera still and lets it run, then holds on the finished board.
import { chromium } from 'playwright';

const REPO = 'C:/Users/aryaa/Documents/Milexium';
const PAGE = `file:///${REPO}/aletheia/artifacts/reel/tty.html`;
const OUT = process.argv[2] || `${REPO}/aletheia/artifacts/reel/recording`;
const W = 1920, H = 1080;
// The page finishes painting at ~22s; anything past ~28s is dead air, so the
// build script trims to 28 rather than recording a long tail.
const RUNTIME_MS = 62_000;   // full session incl. spinners, board, denial
const HOLD_MS = 6_000;       // hold on the architecture

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: W, height: H },
  recordVideo: { dir: OUT, size: { width: W, height: H } },
  deviceScaleFactor: 2,
});
const page = await context.newPage();
await page.goto(PAGE, { waitUntil: 'load' });
await page.waitForTimeout(RUNTIME_MS + HOLD_MS);

await context.close();
await browser.close();
console.log(`tty session written under: ${OUT}`);
