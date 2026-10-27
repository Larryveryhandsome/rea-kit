const SAMPLE_CSV = `id,transaction,area,price,property_type,rooms,url,listed_at
L-001,buy,中央區,1180,apartment,2,https://example.test/L-001,2026-10-01
L-002,buy,東區,1050,apartment,2,https://example.test/L-002,2026-10-01
L-003,buy,中央區,1500,apartment,3,https://example.test/L-003,2026-10-01
L-004,buy,中央區,1100,townhouse,3,https://example.test/L-004,2026-10-01`;

let listings = [];
const $ = (selector) => document.querySelector(selector);

function track(event, metadata = {}) {
  // The public page emits a browser event only. Persistence belongs to the future web layer.
  window.dispatchEvent(new CustomEvent("rea-kit-event", { detail: { event, metadata } }));
}

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (ch === "," && !quoted) { row.push(cell.trim()); cell = ""; }
    else if (ch === "\n" && !quoted) { row.push(cell.trim()); rows.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  if (quoted) throw new Error("CSV 引號沒有關閉");
  if (cell || row.length) { row.push(cell.trim()); rows.push(row); }
  if (rows[0]?.[0]) rows[0][0] = rows[0][0].replace(/^\uFEFF/, "");
  if (rows.length < 2) throw new Error("CSV 至少需要標題列與一筆物件");
  const headers = rows[0];
  const required = ["id", "transaction", "area", "price", "property_type", "rooms", "url", "listed_at"];
  const missing = required.filter((field) => !headers.includes(field));
  if (missing.length) throw new Error(`CSV 缺少欄位：${missing.join("、")}`);
  return rows.slice(1).filter((row) => row.some(Boolean)).map((row) => Object.fromEntries(headers.map((header, i) => [header, row[i] || ""])));
}

function match(need) {
  const max = Number(need.budget);
  const rooms = Number(need.rooms);
  if (!Number.isFinite(max) || max <= 0 || !Number.isFinite(rooms) || rooms < 0) throw new Error("請填有效預算與房數");
  return listings.map((item) => {
    const reasons = [];
    if (item.transaction.toLowerCase() !== "buy") reasons.push("不是買賣物件");
    if (item.area !== need.area) reasons.push("區域不同");
    if (!item.price || !Number.isFinite(Number(item.price)) || Number(item.price) <= 0) reasons.push("缺少有效價格");
    else if (Number(item.price) > max) reasons.push("超過預算");
    if (item.property_type !== need.property_type) reasons.push("類型不同");
    if (!item.rooms || !Number.isFinite(Number(item.rooms))) reasons.push("缺少房數");
    else if (Number(item.rooms) < rooms) reasons.push("房數不足");
    if (!/^https?:\/\//i.test(item.url || "")) reasons.push("缺少有效連結");
    return { item, reasons, priority: reasons.length === 0 };
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));
}

function renderResults(results) {
  const priority = results.filter((row) => row.priority);
  const review = results.filter((row) => !row.priority && row.reasons.length <= 1);
  $("#result-empty").classList.add("hidden");
  $("#result-content").classList.remove("hidden");
  $("#result-count").textContent = `${results.length} 筆已分析`;
  $("#priority-count").textContent = priority.length;
  $("#review-count").textContent = review.length;
  $("#result-list").innerHTML = results.map(({ item, reasons, priority: isPriority }) => `
    <div class="result-row ${isPriority ? "" : "review"}">
      <div><strong>${escapeHtml(item.id)} · ${escapeHtml(item.area)} · ${escapeHtml(item.price)} 萬</strong><small>${isPriority ? "符合目前需求" : escapeHtml(reasons.join("、"))}</small></div>
      <span class="score">${isPriority ? "優先" : "待看"}</span>
    </div>`).join("");
}

function runMatch() {
  const data = new FormData($("#need-form"));
  const need = { area: data.get("area").trim(), budget: data.get("budget"), rooms: data.get("rooms"), property_type: data.get("property_type") };
  if (!listings.length) listings = parseCsv(SAMPLE_CSV);
  renderResults(match(need));
  track("first_result", { count: listings.length });
}

$("#need-form").addEventListener("submit", (event) => { event.preventDefault(); runMatch(); });
$("#load-sample").addEventListener("click", () => { listings = parseCsv(SAMPLE_CSV); $("#csv-file").value = ""; track("sample_imported", { count: listings.length }); runMatch(); });
$("#csv-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try { listings = parseCsv(await file.text()); track("sample_imported", { count: listings.length, source: "local-file" }); runMatch(); }
  catch (error) { listings = []; alert(error.message); }
});
$("#share-result").addEventListener("click", async () => {
  const text = `房仲工作流配對結果：${$("#priority-count").textContent} 筆優先審核，${$("#review-count").textContent} 筆待補資料。`;
  try { await navigator.clipboard.writeText(text); $("#share-result").textContent = "已複製結果摘要"; } catch { $("#share-result").textContent = text; }
  track("share_clicked");
});
track("landing_view", { page: "listing-matching" });
