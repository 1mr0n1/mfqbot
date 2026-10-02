const {JSDOM} = require("jsdom"); const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8"); const sleep = ms => new Promise(r => setTimeout(r, ms));
async function run(name, api, behave, expect, online = true) {
  const dom = new JSDOM(html, {url: "https://dashboard.example/" + (api ? "#api=" + api : ""), runScripts: "dangerously", pretendToBeVisual: true,
    beforeParse(w) { Object.defineProperty(w.navigator, "onLine", {get: () => online}); if (name.includes("token")) w.localStorage.apiToken = "wrong"; w.fetch = behave; }});
  await sleep(2500);
  const d = dom.window.document, text = d.getElementById("whytext").textContent + " | " + d.getElementById("whyfix").textContent;
  const good = !d.getElementById("why").hidden && expect.test(text) && /not connected/.test(d.getElementById("chips").textContent + d.getElementById("status").textContent);
  console.log((good ? "ok    " : "FAIL  ") + name + (good ? "" : "   [" + text.slice(0, 200) + "]"));
  const saved = dom.window.localStorage.apiBase; dom.window.close(); return [good, saved];
}
(async () => {
  const dead = async () => { throw new TypeError("Failed to fetch"); };
  const r = [];
  r.push((await run("nothing answers at a Cloudflare address", "https://x-y-z.trycloudflare.com", dead, /temporary Cloudflare address/))[0]);
  r.push((await run("nothing answers at a Tailscale address", "https://mac.tail1234.ts.net", dead, /Tailscale|Funnel/))[0]);
  r.push((await run("this device is offline", "https://mac.tail1234.ts.net", dead, /device is offline/, false))[0]);
  r.push((await run("no address set at all", "", dead, /No backend address/))[0]);
  r.push((await run("token refused", "https://mac.tail1234.ts.net", async () => new Response("{}", {status: 401}), /refused the token/))[0]);
  r.push((await run("tunnel up, backend down", "https://mac.tail1234.ts.net", async () => new Response("bad gateway", {status: 502}), /backend behind it does not answer/))[0]);
  const corsOnly = async (u, o) => { if (o && o.mode === "no-cors") return new Response("", {status: 200}); throw new TypeError("Failed to fetch"); };
  r.push((await run("address answers but refuses this site", "https://mac.tail1234.ts.net", corsOnly, /answers, but not with anything/))[0]);
  const [, saved] = await run("link with #api= saves the address", "https://mac.tail1234.ts.net", dead, /./);
  const linkOk = saved === "https://mac.tail1234.ts.net"; console.log((linkOk ? "ok    " : "FAIL  ") + "the #api= link stores the address in the browser"); r.push(linkOk);
  console.log(`${r.filter(Boolean).length} of ${r.length} connection checks passed`); process.exit(0);
})();
