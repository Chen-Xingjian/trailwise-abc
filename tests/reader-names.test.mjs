import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {factName, readerAnswer, readerText, monitoredName} from "../app/static/reader-names.mjs";

test("every published fact and monitored source has a descriptive name", () => {
  const corpus = readFileSync(new URL("../documents/abc-six-day/facts.jsonl", import.meta.url), "utf8");
  const names = corpus.trim().split("\n").map(line => factName(JSON.parse(line).fact_id));
  assert.ok(!names.includes("Trail information"));
  assert.equal(new Set(names).size, names.length);
  const watch = JSON.parse(readFileSync(new URL("../config/abc_source_watch.json", import.meta.url)));
  assert.ok(watch.every(item => monitoredName(item.id) !== "Monitored source"));
});

test("route names and source numbers preserve the claim-to-source link", () => {
  const records = [{fact_id:"G06"}, {fact_id:"KT-D5-E"}];
  const text = "On ABC-KT-06, trekking poles are optional [G06].";
  assert.equal(readerAnswer(text, records), "On the six-day Annapurna Base Camp trek from Siwai, trekking poles are optional.");
  assert.match(readerAnswer(text, records, true), /optional \[1\]\./);
  assert.match(readerAnswer("See [G06, KT-D5-E].", records, true), /\[1, 2\]/);
  assert.match(readerAnswer("Claim [KT-D9-X].", records), /unverified source/);
  assert.equal(readerText("G07"), "Footwear for snow or ice above Deurali");
  assert.equal(readerText("ABC and GPS"), "ABC and GPS");
});
