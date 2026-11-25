# Documents used by the ABC assistant

The input to retrieval is the [reviewed ABC six-day release](abc-six-day/manifest.json). The 85 presentation records cover route planning, equipment, season and weather context, and preparation. There are 20 source records. Some statements concern a single party or a general preparation principle. Each record carries its own scope.

| File | What to check |
| --- | --- |
| [facts.jsonl](abc-six-day/facts.jsonl) | One accepted English statement per line. Read its route reference, direction, value and qualification together. |
| [sources.jsonl](abc-six-day/sources.jsonl) | Match the source ID to the publisher, URL, licence, attribution and rights review. The fact's provenance gives the location within that source. |
| [scope.json](abc-six-day/scope.json) | Route references, limitations and rules for checking dynamic information. |
| [manifest.json](abc-six-day/manifest.json) | Release ID, allowed IDs, file hashes, exclusions and suspended fields. |
| [ATTRIBUTION.txt](abc-six-day/ATTRIBUTION.txt) | Credits and source-specific terms for this local coursework release. |

For example, find K07 in the facts and follow its O01 provenance to KeiTreks, *Annapurna Base Camp → whole-route summary → Days 6*. Six walking days is the publisher's reference itinerary. For day-five timing, compare KT-D5-M with KT-D5-E. The two records distinguish time moving from time between the first and last fix.

The loader indexes one chunk per accepted fact and attaches its provenance. It does not recursively ingest this directory. K09 and the suspended distance fields stay outside retrieval. Current forecasts and bulletins are fetched separately in chat. Evaluation questions and answers live in the outputs area. A future release goes through the [cleaning and review workflow](../docs/CLEANING_AND_INGESTION.md) before selection.
