import assert from "node:assert/strict";
import test from "node:test";
import {conversationStore, modelOnlyHistory} from "../app/static/chat-store.mjs";

class Storage {
  setItem(k,v) { this[k] = v; }
  getItem(k) { return this[k] ?? null; }
  removeItem(k) { delete this[k]; }
}
test("reload restores branches and deletion cannot revive an old chat", () => {
  const storage = new Storage(), store = conversationStore(storage);
  const a = store.create(), b = store.create();
  store.append(a.id, {id:"one", parent:null, data:{trail_focus:{places:["Deurali"]}}});
  store.append(a.id, {id:"two", parent:"one"});
  store.append(a.id, {id:"three", parent:"one"});
  const fresh = conversationStore(storage);
  assert.deepEqual(fresh.read(a.id).turns.map(t => t.parent),[null,"one","one"]);
  assert.equal(fresh.read(a.id).turns[0].data.trail_focus.places[0],"Deurali");
  fresh.remove(a.id);
  assert.equal(store.append(a.id,{id:"late"}),null);
  assert.deepEqual(store.list().map(c => c.id),[b.id]);
});
test("unavailable browser storage leaves the session usable", () => {
  const store = conversationStore(null), chat = store.create();
  store.append(chat.id,{id:"one"}); assert.equal(store.read(chat.id).turns.length,1);
  store.remove(chat.id); assert.equal(store.list().length,0);
});

test("model-only history follows the chosen parent and excludes guide evidence and sibling answers", () => {
  const turn = (id, parent) => ({id, parent, mode: "compare", question: "question " + id,
    data: {rag: {answer: "private evidence"}, baseline: {answer: "model " + id, answer_kind: "llm"}}});
  const turns = [turn("a", null), turn("b", "a"), turn("c", "a")];
  assert.deepEqual(modelOnlyHistory(turns, turns[2]), [
    {question: "question a", answer: "model a"}, {question: "question c", answer: "model c"}]);
});
