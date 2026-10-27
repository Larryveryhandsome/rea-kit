const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const context = vm.createContext({
  document: {querySelector: () => ({addEventListener() {}})},
  window: {dispatchEvent() {}}, CustomEvent: class {},
});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8"), context);
assert.equal(vm.runInContext("escapeHtml('<img src=x onerror=alert(1)>')", context), "&lt;img src=x onerror=alert(1)&gt;");
const input = 'id,transaction,area,price,property_type,rooms,url,listed_at\nA,buy,區,1000,apartment,2,https://example.test/a,2026-10-01\n';
context.input = input.replace(",區,", ',"區,含逗號",');
assert.equal(vm.runInContext("parseCsv(input)[0].area", context), "區,含逗號");
vm.runInContext("listings = parseCsv(input); listings[0].price = '';", context);
assert.equal(vm.runInContext("match({budget:1200,rooms:2,area:'區,含逗號',property_type:'apartment'})[0].priority", context), false);
console.log("PASS: CSV quoted fields, HTML escaping, missing-price rejection");
