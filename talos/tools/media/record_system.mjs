// Record the system diagram assembling itself, edge → core → evidence → surface,
// then the agent worker pool landing underneath. Holds on the finished board so
// the last frame is usable as a still.
import { chromium } from 'playwright';

const REPO = 'C:/Users/aryaa/Documents/Milexium';
const PAGE = `file:///${REPO}/aletheia/artifacts/reel/system.html`;
const OUT = process.argv[2] || `${REPO}/aletheia/artifacts/reel/recording`;
const W = 1920, H = 716;

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: W, height: H },
  recordVideo: { dir: OUT, size: { width: W, height: H } },
  deviceScaleFactor: 2,
});
const page = await context.newPage();
await page.goto(PAGE, { waitUntil: 'load' });

// the script self-assembles in ~34s; hold the finished board for 6s
await page.waitForTimeout(40000);

await context.close();
await browser.close();
console.log(`video written under: ${OUT}`);
