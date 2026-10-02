// Drives the dashboard page in a headless DOM: real data is read from the live backend, but everything the page
// tries to POST is recorded instead of sent — so every button can be pressed without touching Telegram.
const {JSDOM} = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const BASE = "http://127.0.0.1:8000";
const posts = [];
let extraEvents = [];
const results = [];
const ok = (name, cond, detail) => { results.push([!!cond, name, detail || ""]); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const dom = new JSDOM(html, {url: BASE + "/admin", runScripts: "dangerously", pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = async (url, opts) => {
        const full = new URL(url, BASE).toString();
        if (opts && opts.method === "POST") { posts.push({path: new URL(full).pathname, body: opts.body ? JSON.parse(opts.body) : {}}); return new Response("{}", {status: 200}); }
        const r = await fetch(full, opts);
        if (new URL(full).pathname === "/admin/events" && extraEvents.length) {
          const data = await r.json(); data.events = data.events.concat(extraEvents); extraEvents = [];
          return new Response(JSON.stringify(data), {status: 200});
        }
        return r;
      };
    }});
  const w = dom.window, d = w.document, $ = id => d.getElementById(id);
  const click = el => el.dispatchEvent(new w.MouseEvent("click", {bubbles: true}));
  const change = (el, v) => { el.value = v; el.dispatchEvent(new w.Event("change", {bubbles: true})); };
  const last = () => posts[posts.length - 1] || {};
  const jsErrors = []; w.addEventListener("error", e => jsErrors.push(e.message));
  await sleep(3500);
  const status = await (await fetch(BASE + "/admin/status")).json();

  // header
  ok("connected dot is on", $("dot").classList.contains("on"));
  ok("status line names the account", $("status").textContent.includes(status.account), $("status").textContent);
  ok("no 'not connected' box", $("why").hidden);
  ok("model chips shown", $("chips").textContent.includes(status.models[0]), $("chips").textContent);
  click($("pause")); await sleep(50); ok("Pause → pause/resume command", last().body.type === (status.paused ? "resume" : "pause"), JSON.stringify(last()));
  click($("approve")); await sleep(50); ok("Approve button → approve command", last().body.type === "approve" && last().body.value === (status.approve ? "off" : "on"), JSON.stringify(last()));
  ok("connection panel hidden at first", $("conn").hidden); click($("connbtn")); ok("⚙︎ opens the connection panel", !$("conn").hidden); click($("connbtn")); ok("⚙︎ closes it again", $("conn").hidden);

  // order box
  $("order").value = "что писала мама?"; click($("orderdo")); await sleep(50);
  ok("Do it → do command with the text", last().body.type === "do" && last().body.text === "что писала мама?", JSON.stringify(last()));
  ok("order box cleared after sending", $("order").value === "");
  $("order").value = "тест enter"; $("order").dispatchEvent(new w.KeyboardEvent("keydown", {key: "Enter", bubbles: true})); await sleep(50);
  ok("Enter in the order box sends it", last().body.text === "тест enter");
  const before = posts.length; $("order").value = "   "; click($("orderdo")); await sleep(50); ok("empty order is not sent", posts.length === before);
  click($("orderyes")); await sleep(50); ok("Yes → do 'yes'", last().body.type === "do" && last().body.text === "yes");
  click($("orderno")); await sleep(50); ok("No → do 'no'", last().body.text === "no");

  // settings
  const toggles = [...$("toggles").querySelectorAll(".toggle")];
  ok("every switch is shown", toggles.length === status.toggles.length, `${toggles.length} vs ${status.toggles.length}`);
  ok("switch positions match the bot", status.toggles.every((t, i) => toggles[i].classList.contains("on") === t.on));
  let allToggle = true;
  for (let i = 0; i < toggles.length; i++) {
    const wasOn = toggles[i].classList.contains("on"); click(toggles[i]); await sleep(30);
    const b = last().body; if (!(b.type === "toggle" && b.value === status.toggles[i].key && b.text === (wasOn ? "off" : "on"))) { allToggle = false; ok("switch " + status.toggles[i].key, false, JSON.stringify(b)); }
  }
  ok("each switch sends its own on/off command", allToggle);

  // chats
  const chatRows = [...$("chats").querySelectorAll(".chatrow")];
  ok("every chat has a row", chatRows.length === status.chats.length, `${chatRows.length} vs ${status.chats.length}`);
  const visible = () => [...$("chats").querySelectorAll(".chatrow")].filter(r => !r.hidden).length;
  if (chatRows.length > 4) {
    ok("chat list folded to 4", visible() === 4, String(visible()));
    const more = $("chatsmore"); ok("'Show all N' button", more && /Show all/.test(more.textContent), more && more.textContent);
    click(more); ok("Show all shows every chat", visible() === chatRows.length); ok("button turns into Show less", /Show less/.test(more.textContent));
    click(more); ok("Show less folds again", visible() === 4);
  }
  const row = [...$("chats").querySelectorAll(".chatrow")][0], rowName = row.querySelector(".name").textContent;
  change(row.querySelector("select"), "manual"); await sleep(30); ok("chat mode select → mode command", last().body.type === "mode" && last().body.value === "manual" && last().body.chat === rowName, JSON.stringify(last()));
  click(row.querySelector(".answer")); await sleep(30); ok("Answer now → answer command for that chat", last().body.type === "answer" && last().body.chat === rowName);
  const inp = row.querySelector("input"); inp.value = "привет с панели"; click(row.querySelector(".say")); await sleep(30);
  ok("Send → say command with the text", last().body.type === "say" && last().body.text === "привет с панели" && last().body.chat === rowName); ok("chat text box cleared", inp.value === "");
  inp.value = "через enter"; inp.dispatchEvent(new w.KeyboardEvent("keydown", {key: "Enter", bubbles: true})); await sleep(30); ok("Enter in a chat box sends", last().body.text === "через enter");
  const n1 = posts.length; inp.value = ""; click(row.querySelector(".say")); await sleep(30); ok("empty chat text is not sent", posts.length === n1);

  // groups
  const gRows = [...$("groups").querySelectorAll(".chatrow")];
  ok("every group has a row", gRows.length === (status.groups || []).length, `${gRows.length} vs ${(status.groups || []).length}`);
  if (gRows.length) {
    const g = status.groups.find(x => x.name === gRows[0].querySelector(".name").textContent);
    ok("group switch shows the real state", gRows[0].querySelector("select").value === (g.on ? "on" : "off"));
    change(gRows[0].querySelector("select"), g.on ? "off" : "on"); await sleep(30); ok("group select → group command", last().body.type === "group" && last().body.chat === String(g.id) && last().body.value === (g.on ? "off" : "on"), JSON.stringify(last()));
    click(gRows[0].querySelector(".answer")); await sleep(30); ok("group Answer now → ganswer", last().body.type === "ganswer" && last().body.chat === String(g.id));
    const gi = gRows[0].querySelector("input"); gi.value = "в группу"; click(gRows[0].querySelector(".say")); await sleep(30); ok("group Send → gsay with the text", last().body.type === "gsay" && last().body.text === "в группу");
  }

  // people
  const pRows = [...$("people").querySelectorAll(".chatrow")];
  ok("every person has a row", pRows.length === (status.people || []).length, `${pRows.length} vs ${(status.people || []).length}`);
  if (pRows.length) {
    const p = status.people[0];
    ok("person closeness shown", pRows[0].querySelector("select").value === p.closeness, pRows[0].querySelector("select").value + " vs " + p.closeness);
    change(pRows[0].querySelector("select"), "close"); await sleep(30); ok("closeness select → person command", last().body.type === "person" && last().body.chat === String(p.id) && last().body.value === "close", JSON.stringify(last()));
  }

  // log
  const rowsIn = () => $("log").querySelectorAll(".row").length;
  const viewBtn = v => [...$("view").querySelectorAll("button")].find(b => b.dataset.v === v);
  click(viewBtn("all")); const all = rowsIn(); click(viewBtn("messages")); const msgs = rowsIn(); click(viewBtn("problems")); const probs = rowsIn();
  ok("Everything shows at least as much as Messages", all >= msgs, `${all} / ${msgs} / ${probs}`);
  ok("Messages view holds only messages", (click(viewBtn("messages")), [...$("log").querySelectorAll(".badge")].every(b => /they wrote|bot sent/.test(b.textContent))));
  ok("Problems view holds only problems", (click(viewBtn("problems")), [...$("log").querySelectorAll(".badge")].every(b => /warning|cancelled/.test(b.textContent))));
  ok("the pressed view button is highlighted", viewBtn("problems").classList.contains("on") && !viewBtn("messages").classList.contains("on"));
  click(viewBtn("all"));
  const opts = [...$("filter").options].map(o => o.value).filter(Boolean);
  if (opts.length) { change($("filter"), opts[0]); ok("chat filter narrows the log to one chat", [...$("log").querySelectorAll(".chat")].every(c => c.textContent === opts[0]), opts[0]); change($("filter"), ""); }
  click($("clear")); ok("Clear view empties the log", rowsIn() === 0);

  // drafts: a held draft arrives → card; edit, send now, cancel
  const eid = 10 ** 9, ts = Date.now() / 1000;
  extraEvents = [{id: eid, ts, kind: "draft", chat: "Test chat", text: "привет\nкак дела", data: {draft_id: "d-test-1", parts: ["привет", "как дела"], hold: 30, approve: false}},
                 {id: eid + 1, ts, kind: "draft", chat: "Test chat 2", text: "ок", data: {draft_id: "d-test-2", parts: ["ок"], hold: 30, approve: true}}];
  await sleep(1800);
  const cards = [...$("drafts").querySelectorAll(".draft")];
  ok("a draft shows up as a card", cards.length === 2, String(cards.length)); ok("'Nothing queued' is hidden meanwhile", $("nodrafts").hidden);
  const card = cards.find(c => c.querySelector(".who").textContent.includes("Test chat") && !c.querySelector(".who").textContent.includes("2"));
  const ta = card.querySelector("textarea");
  ok("draft text is editable, one message per line", ta.value === "привет\nкак дела");
  ok("countdown shown", /sending in/.test(card.querySelector(".phase").textContent), card.querySelector(".phase").textContent);
  ta.value = "привет\nчё как"; ta.dispatchEvent(new w.Event("input", {bubbles: true})); await sleep(400);
  ok("typing saves the edit and freezes the countdown", last().path === "/admin/drafts/d-test-1/edit" && last().body.editing === true && last().body.parts[1] === "чё как", JSON.stringify(last()));
  await sleep(200); ok("card says it waits for Send now", /editing/.test(card.querySelector(".phase").textContent), card.querySelector(".phase").textContent);
  click(card.querySelector(".send")); await sleep(100); ok("Send now posts the edited text", last().path === "/admin/drafts/d-test-1/send" && last().body.parts.join("|") === "привет|чё как", JSON.stringify(last()));
  const card2 = cards.find(c => c !== card);
  await sleep(200); ok("approve-mode draft says it waits for you", /waiting for you/.test(card2.querySelector(".phase").textContent), card2.querySelector(".phase").textContent);
  click(card2.querySelector(".cancel")); await sleep(100); ok("Cancel posts cancel", last().path === "/admin/drafts/d-test-2/cancel");
  extraEvents = [{id: eid + 2, ts, kind: "sent", chat: "Test chat", text: "привет", data: {draft_id: "d-test-1", final: true}},
                 {id: eid + 3, ts, kind: "cancelled", chat: "Test chat 2", text: "cancelled", data: {draft_id: "d-test-2"}}];
  await sleep(1800);
  ok("cards disappear once sent / cancelled", $("drafts").querySelectorAll(".draft").length === 0, String($("drafts").querySelectorAll(".draft").length));
  ok("no script errors on the page", jsErrors.length === 0, jsErrors.join("; "));

  let bad = 0; for (const [good, name, detail] of results) { if (!good) { bad++; console.log("FAIL  " + name + (detail ? "   [" + detail.slice(0, 160) + "]" : "")); } }
  console.log(`${results.length - bad} of ${results.length} dashboard checks passed`);
  w.close(); process.exit(0);
})().catch(e => { console.log("TEST CRASHED", e); process.exit(1); });
