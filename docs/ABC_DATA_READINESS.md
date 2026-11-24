# ABC evidence review for planning questions

Working paper for human review · 18 November 2026 · Local release NEPAL-RAG-LOCAL-20261118-01

## What a planner can substantiate today

| Question | Evidence in the local release | Answer boundary |
|---|---|---|
| What is one documented ABC itinerary? | K07 gives six walking days for KeiTreks' Siwai return reference. K08 supplies the ordered endpoints below. | Label the publisher's version. Total trip duration, overnight stays, fitness requirements and walking hours need separate evidence. |
| Which places does the Sanctuary corridor description connect? | W01–W04 give ordered places for the Wikivoyage reference, including MBC to ABC. | Keep the corridor ordering separate from the KeiTreks daily itinerary. Shared place names alone cannot transfer measurements. |
| Does this version meet the project's over-10-km criterion? | K09 excluded. K01–K06 distance use suspended. | A version-matched measurement with a documented method is still needed to substantiate the criterion. |
| What should I pack for a specific month? | No admitted equipment rules or monthly climate records. | Collect an equipment rationale and evidence that its conditions apply to this trip. |
| What will conditions be on my departure date? | No weather feed or approved weather snapshot. | A forecast needs place, elevation or documented coverage, issue time and validity covering the requested date. Seasonal summaries answer a different question. |
| Can my past experience help me prepare? | No admitted preparation guidance or stage-load measurements. | Trip preferences can refine the question. Evidence about stage load and general preparation is needed to explain a comparison. Individual medical clearance is outside scope. |

### First review item · K08

Derived from adjacent places in the accepted K08 sequence. These are walking-stage labels.

| Day | Walk starts | Walk finishes |
|---|---|---|
| 1 | Siwai | Chhomrong |
| 2 | Chhomrong | Bamboo |
| 3 | Bamboo | Deurali |
| 4 | Deurali | Annapurna Base Camp |
| 5 | Annapurna Base Camp | Bamboo |
| 6 | Bamboo | Siwai |

Check all six pairs against K08 and compare the source locator in its provenance. In particular, Bamboo occurs twice and ABC changes from the destination on day 4 to the departure on day 5. Preserve these distinctions when rendering or retrieving the itinerary. [Accepted records](../data/release/facts.jsonl)

## Sources to investigate before expanding coverage

| Source and original location | Potential use | Decision for this review |
|---|---|---|
| KeiTreks, GPX downloads, and pinned Wikivoyage page | Selected stage and corridor descriptions | Use only the previously accepted fields and their qualifications. Check the per-source attribution and revision. [Registry](../data/release/sources.jsonl) |
| KE Adventure Travel, Annapurna Sanctuary and Poon Hill trip notes, equipment list | First-hand evidence of what one operator asks its participants to bring. Record the operator's route, service inclusions and any seasonal condition. | Candidate for cross-checking. Different itinerary from the Siwai return. Verify rights before importing text or images. [Trip notes](https://www.keadventure.com/holidays/nepal-trekking-annapurna-sanctuary?layout=tripnote&tmpl=component) |
| US National Park Service, Ten Essentials, extra clothing | General equipment functions and conditions | Candidate for general guidance. Establish applicability to Nepal separately. Check item-level authorship and reuse. [Ten Essentials](https://www.nps.gov/articles/10essentials.htm) · [Publication terms](https://www.nps.gov/aboutus/publications.htm) |
| Nepal DHM, Tourism Weather Information, Pokhara–Chhomrong–Annapurna Base Camp route selector | Candidate forecast coverage for the pilot | Verify the selected forecast point, altitude, time zone, issue and validity times, permitted access, retention and display. The default page may show a different route. [Tourism weather](https://tourism.dhm.gov.np/) |
| CDC Yellow Book, High-Altitude Travel and Altitude Illness, susceptibility and risk factors | General distinction between hiking endurance and altitude-illness susceptibility | Candidate for an answer boundary. Check chapter-specific reuse terms. No personal prediction from fitness or training history. [Chapter](https://www.cdc.gov/yellow-book/hcp/environmental-hazards-risks/high-altitude-travel-and-altitude-illness.html) |

## From collection to acceptance

1. Identify the question and the smallest claim needed. Record author/publisher, primary or derivative source, exact URL and section, date or revision, applicable route and permitted uses. Record upstream lineage so copied pages do not count as independent corroboration.
2. A fetcher can detect a revision and stage permitted material. Attach original units and wording locator to any model-extracted candidate. Keep acquisition time separate from publication, observation or forecast time. Record missing values explicitly. Check image creator, licence, location and capture date individually if the image supplies evidence.
3. For route geometry, compare endpoints, direction, branches, transport legs and measurement method before comparing numbers. For gear, record the item, its purpose, conditions, audience and whether it is required by one operator or suggested generally. Preserve disagreements with a reason.
4. Use session-only preferences such as walking days, month, past multi-day trips and carried load for personalisation. Keep user records separate from the shared corpus. For live weather, approve the provider, usage and validation rules in advance, then check each response's place and validity at query time.
5. Submit changed static records for the existing hash-bound human review. Release accepted fields, retain superseded versions, and keep candidates outside retrieval. Periodic source checks alone cannot confirm accuracy or ongoing access.

## Acceptance questions to reserve for subsequent trials

| Test | Evidence-based outcome |
|---|---|
| Where does day 5 start and finish on the Siwai version? | ABC to Bamboo, with K08. |
| Can the six-day version be completed in five days by joining two stages? | The publisher specifies six days. Available evidence does not support that modification. |
| Does an operator including Poon Hill require its entire equipment list on every ABC trip? | Identify the operator's version and inclusions. Support any transfer item by item. |
| An in-date forecast covers Pokhara only. What does it establish for ABC tomorrow? | State the coverage gap. Repeat with an expired same-location forecast and a valid matched forecast to distinguish the failure modes. |
| I run marathons. Does that establish low altitude-illness risk? | Keep endurance and altitude susceptibility separate. Treat personal history as context, with no individual clearance. |

After each dataset addition, first ask a reviewer to answer using only that evidence. If evidence suffices, test whether retrieval finds it and generation accurately uses it. A controlled comparison with web-assisted Qwen can use the same source snapshot and questions to test the added value of curated, route-versioned records.
