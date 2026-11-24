// Identifiers cross the API unchanged. Translate them only when writing for readers.
export const routes = {
  "ABC-KT-06": "Annapurna Base Camp · six-day round trip from Siwai",
  "ABC-WV-CORRIDOR": "Annapurna Sanctuary trail · Wikivoyage route guide",
};

const topics = {
  "NPS-DRY-01": "Keeping gear dry inside a pack",
  K07: "Walking days on the Siwai round trip", K08: "Daily stops on the Siwai round trip",
  W01: "The approach from Nayapul", W02: "Chomrong to Dobhan via Bamboo",
  W03: "Dobhan to Machhapuchhare Base Camp", W04: "The final approach to Annapurna Base Camp",
  G01: "Headlamp and spare batteries", G02: "Rain protection and warm layers",
  G03: "Offline maps and a paper backup", G04: "Carrying and treating water",
  G05: "Walking shoes", G06: "Trekking poles on long descents", G07: "Footwear for snow or ice above Deurali",
  G08: "Checking bedding at teahouses", G09: "Checking porter and rental arrangements",
  G10: "Sun protection", G11: "Food between teahouses", G12: "First aid and emergency shelter",
  S01: "Trekking seasons", S02: "Monsoon rainfall", S03: "Winter conditions above Deurali",
  F03: "Comparing practice walks with the trek", F04: "Fitness and altitude illness",
  F05: "Sharing a trip plan",
};
const measures = {
  M: "walking time", E: "elapsed time including stops", "ASC-APPROX": "approximate ascent",
  "DES-APPROX": "approximate descent", "ASC-QUAL": "uphill sections", "DES-QUAL": "downhill sections",
  "TRACK-START": "recorded starting point", "TRACK-FINISH": "recorded finishing point",
};
const locations = {ABC: "Annapurna Base Camp", CHHOMRONG: "Chhomrong", DEURALI: "Deurali"};
const months = "January February March April May June July August September October November December".split(" ");

export function factName(id) {
  if (Object.hasOwn(topics, id)) return topics[id];
  const day = /^KT-D([1-6])-(.+)$/.exec(id);
  if (day && Object.hasOwn(measures, day[2])) return `Day ${day[1]} · ${measures[day[2]]}`;
  const climate = /^S05-(ABC|CHHOMRONG|DEURALI)-(0[1-9]|1[0-2])$/.exec(id);
  if (climate) return `${months[Number(climate[2]) - 1]} climate near ${locations[climate[1]]}`;
  return "Trail information";
}

const licences = {
  "CC-BY-4.0": "Creative Commons Attribution 4.0",
  "CC-BY-SA-4.0": "Creative Commons Attribution-ShareAlike 4.0",
  "ODbL-1.0": "Open Database License 1.0", "US-Gov-PD": "U.S. government public domain",
  "PROJECT-LOCAL-USE": "Local project use",
};
export function licenceName(id) { return licences[id] || id || "Licence not specified"; }

const monitored = {
  "keitreks-index": "KeiTreks · downloadable route tracks", "keitreks-time": "KeiTreks · hiking times",
  "whole-track": "KeiTreks · complete route track", "daily-metrics": "KeiTreks · daily measurements",
  "wikivoyage-current-revision": "Wikivoyage · Annapurna Sanctuary trek",
  "OSM-JHINU-BRIDGE": "OpenStreetMap · Jhinu Danda suspension bridge",
  "OSM-JHINU-STOP": "OpenStreetMap · Jhinu Danda bus stop",
  era5_daily: "Historical climate data", era5_grid_elevation: "Climate grid elevation",
  "NPS-KIT": "National Park Service · Ten Essentials", "NPS-HIKE": "National Park Service · Hike Smart",
  "CDC-ALT": "CDC · high-altitude travel", "NPS-PLAN": "National Park Service · trip planning",
};
export function monitoredName(id) {
  const day = /^track-day-(\d+)$/.exec(id);
  return day ? `KeiTreks · day ${day[1]} track` : monitored[id] || "Monitored source";
}

export function readerText(text) {
  return String(text ?? "")
    .replace(/S05_evidence\/method_and_results\.json/g, "Historical climate methods and results")
    .replace(/\b(?:the (?:standard )?|standard )?ABC-KT-06\b(?: (?:route|reference|itinerary)\b)?/gi, "the six-day Annapurna Base Camp trek from Siwai")
    .replace(/\b(?:the )?ABC-WV-CORRIDOR\b(?: (?:route|reference)\b)?/gi, "the Annapurna Sanctuary route described by Wikivoyage")
    .replace(/\b(?:KT-D\d+-[A-Z]+(?:-[A-Z]+)*|S05-(?:ABC|CHHOMRONG|DEURALI)-\d\d|[KWGSF]\d\d)\b/gi,
      id => factName(id.toUpperCase()));
}

// In the expanded source view each reference number points to the corresponding
// named card. Keep a visible indication if a citation cannot be matched.
export function readerAnswer(text, records, numbered = false) {
  const numbers = new Map(records.map((record, index) => [record.fact_id, index + 1]));
  const citations = /[ \t]*\[([A-Z0-9-]+(?:\s*[,;]\s*[A-Z0-9-]+)*)\]/g;
  return readerText(text.replace(citations, (original, group, offset, full) => {
    const ids = group.split(/\s*[,;]\s*/);
    if (!ids.some(id => numbers.has(id) || /^(?:KT-|S05-|[A-Z]+\d\d)/.test(id))) return original;
    if (ids.some(id => !numbers.has(id))) return " [unverified source]";
    if (numbered) return " [" + ids.map(id => numbers.get(id)).join(", ") + "]";
    // If a citation is used as a noun, give it a readable name.
    if (/^[ \t]+[a-z]/.test(full.slice(offset + original.length))) return " " + ids.map(factName).join(" and ");
    return "";
  })).trim();
}
