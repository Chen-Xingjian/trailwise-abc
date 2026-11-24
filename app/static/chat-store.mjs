// Each conversation has its own key so updating one cannot replace another.
const PREFIX = "trailwise.conversation.v1.";
export function conversationStore(storage) {
  const memory = new Map();
  let persistent = Boolean(storage);
  function read(id) {
    if (persistent) {
      try {
        const raw = storage.getItem(PREFIX + id);
        if (!raw) return null;
        const chat = JSON.parse(raw);
        return chat.id === id && Array.isArray(chat.turns) ? chat : null;
      } catch (error) {
        if (error instanceof SyntaxError) return null;
        persistent = false;
      }
    }
    return memory.get(id) || null;
  }
  function save(chat) {
    memory.set(chat.id, chat);
    if (persistent) {
      try { storage.setItem(PREFIX + chat.id, JSON.stringify(chat)); }
      catch { persistent = false; }
    }
    return chat;
  }
  function list() {
    if (persistent) {
      try {
        for (const key of Object.keys(storage)) {
          if (key.startsWith(PREFIX)) {
            const chat = read(key.slice(PREFIX.length));
            if (chat) memory.set(chat.id, chat);
          }
        }
        if (persistent) for (const id of memory.keys()) if (!storage.getItem(PREFIX + id)) memory.delete(id);
      } catch { persistent = false; }
    }
    return [...memory.values()].sort((a, b) => b.updated - a.updated);
  }
  function create() {
    return save({id: crypto.randomUUID(), updated: Date.now(), turns: []});
  }
  function append(id, turn) {
    const chat = read(id);
    if (!chat) return null;
    return save({...chat, updated: Date.now(), turns: [...chat.turns, turn]});
  }
  function remove(id) {
    // A failed delete must not be presented to the user as a successful one.
    if (storage) storage.removeItem(PREFIX + id);
    memory.delete(id);
  }
  return {read, list, create, append, remove, persistent: () => persistent, prefix: PREFIX};
}

// Traverse only the selected reply branch. Never send the guide's answer to the control.
export function modelOnlyHistory(turns, parent) {
  const history = [];
  for (let turn = parent; turn && history.length < 3; turn = turns.find(item => item.id === turn.parent)) {
    const response = turn.mode === "compare" ? turn.data.baseline : turn.mode === "baseline" ? turn.data : null;
    if (response?.answer && response.answer_kind !== "error") {
      history.unshift({question: turn.question.slice(0, 1200), answer: response.answer.slice(0, 1800)});
    }
  }
  return history;
}
