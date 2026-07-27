// Record the layer-flow reel. The page animates on its own timers, so this just
// opens it, holds the camera still, and lets it run to the end.
import { chromium } from 'playwright';

const REPO = 'C:/Users/aryaa/Documents/Milexium';
const PAGE = `file:///${REPO}/aletheia/artifacts/reel/reel.html`;
const OUT = `${REPO}/aletheia/artifacts/reel/recording`;
const RUNTIME_MS = 34_000; // sequence length + tail

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1600, height: 900 },
  recordVideo: { dir: OUT, size: { width: 1600, height: 900 } },
  deviceScaleFactor: 2,
});
const page = await context.newPage();
await page.goto(PAGE, { waitUntil: 'load' });
await page.waitForTimeout(RUNTIME_MS);
await context.close();
await browser.close();
console.log(`reel written under: ${OUT}`);
