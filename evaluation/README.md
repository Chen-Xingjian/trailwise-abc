# First development comparison

This folder contains evaluation material, **never retrieval content**. The first protocol uses six human-accepted documentary facts from the unchanged R03 review snapshot. It does not admit pending altitude, Poon Hill or village records, and it does not restore excluded distances.

`development.json` contains eight English development questions, their reference answers, exact evidence IDs and three-point rubrics:

| Group | Items | Maximum |
| --- | --- | --- |
| Factual | D01, D02, D03, D04, D06, D08 | 18 |
| Boundary | D09, D12 | 6 |

The protocol and first implementation scope were selected under the user's request to complete preparation and begin a local prototype. Existing fact acceptance comes from the R03 records; no separate human acceptance of answer keys is invented. The dataset starts `NOT_RUN`, with null scores and `executed=false`. Each item's `executable_now=false` records that implementation preflight has not occurred. This is an implementation requirement, not a request for another permission step: the user has authorized real local development runs once a genuine model is configured.

## Run and grade fairly

1. Validate the release manifest and report the actual six IDs loaded. Use an explicitly selected release, not a recursive scan of project folders.
2. Check the actual local model connection. Save the model identifier, quantization when known, shared prompt, parameters and release checksum. Do not treat an evidence preview or mock as an LLM run.
3. Run both conditions against the same questions and common scope instruction. Only the RAG condition receives retrieved evidence. Neither condition browses or uses live tools.
4. Save unedited answers, retrieved IDs, latency and errors. A failed or unavailable run stays missing and is not graded as success.
5. Human-grade the shared content rubric. Prefer answers presented in randomized order with condition labels hidden where practical. Store human grades separately from this answer-key file.
6. Report the factual subtotal out of 18 and boundary subtotal out of 6. Analyze RAG retrieval coverage and citation support separately; a baseline answer is not wrong merely because it has no citations.

The boundary questions partly test shared scope instructions. They must not be used by themselves to claim RAG superiority. The six documentary facts are enough to test an implementation, not enough to demonstrate broad planning usefulness, a verified route over 10 km or accident reduction. New rights-cleared complete-route evidence is a later data iteration.

## Update the protocol

Keep this development set separate from any unseen final evaluation. Adding an accepted fact does not automatically validate a new question or answer. Register exact evidence IDs and hashes, check the rubric, create a new dataset version, then log actual runs. If the implementation uses a new release or changes retrieval/generation settings, identify the version in the run record.

`build_development_subset.py` reproduces this subset from the local R03 snapshot without editing it. Its original source path need not exist on another machine to use the checked-in `development.json`; it is needed only to reproduce its provenance export.
