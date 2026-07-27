import { chromium } from 'playwright';
const REPO='C:/Users/aryaa/Documents/Milexium';
const OUT=`${REPO}/aletheia/artifacts/reel/recording`;
const b = await chromium.launch();
const c = await b.newContext({
  viewport:{width:1920,height:812},
  recordVideo:{dir:OUT,size:{width:1920,height:812}},
  deviceScaleFactor:2,
});
const p = await c.newPage();
await p.goto(`file:///${REPO}/aletheia/artifacts/reel/architecture.html`,{waitUntil:'load'});
await p.waitForTimeout(38000);   // assembly + hold on the finished diagram
await c.close(); await b.close();
console.log('architecture reel recorded');
