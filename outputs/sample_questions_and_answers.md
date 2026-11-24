# Sample questions and answers

These are the original English outputs from the frozen R38 comparison of candidate R37. The scores are provisional. Each example links a user question to the retrieved evidence and to the recorded baseline under the same evaluation.

Across the 16 main scoring turns the RAG application scored 19/32 and the baseline 12/32, with seven wins, seven ties and two losses. The two opening turns were scored separately. The candidate missed the release gate. These scores apply to this question set and candidate. The installed chat and its live lookups have a separate execution path.

## Z01 · Two different clocks on the return to Bamboo

**User input**

For the KeiTreks return from base camp to Bamboo, I want two entries in my diary: time actually walking, and time from departure until arrival. What did that party record?

**Retrieved fact IDs, in order**  KT-D5-E, KT-D5-M, KT-D6-E

**RAG answer · 2/2**

> For the KeiTreks return from Annapurna Base Camp to Bamboo on Day 5, the recorded times are:
> *   **Time actually walking (moving time):** 7 hours and 12 minutes [KT-D5-M].
> *   **Time from departure until arrival (door-to-door elapsed time):** 8 hours and 4 minutes [KT-D5-E].
>
> *Note: These figures represent a single publisher observation where stage endpoints are labeled by the publisher; individual travel times may differ.*

**Baseline answer · 0/2**

> No record exists in the provided evidence or available data to confirm the specific times recorded by a "KeiTreks" party for the return leg from Base Camp to Bamboo. Without a cited fact ID (e.g., [K08]) establishing the exact trail section, the specific party's logs, or the validity period of such a report, I cannot state what that party recorded. Any specific duration or time entry would be an unsupported fabrication.

The two time values are supported by separate records for the same stage and direction. The records describe one party.

## Z03 · Five confirmed walking days

**User input**

My leave for the Siwai round trip is eight days, including the transfers. Can I commit to the whole walk on that basis?

The vehicle bookings are now fixed. Five full days remain for walking, and my leave cannot move. What should I plan for?

**Retrieved fact IDs, in order**  K07, F03, K08

**RAG answer · 0/2**

> After allowing for travel both ways, when can you start walking at the trailhead and when must you finish there? Approximate dates and times, or the parts of days available for hiking, are enough.

**Baseline answer · 0/2**

> After allowing for travel both ways, when can you start walking at the trailhead and when must you finish there? Approximate dates and times, or the parts of days available for hiking, are enough.

The opening clarification scored 2/2 for both arms. On the second turn the user supplied five full walking days. K07 was retrieved, but the application repeated the opening question. It missed the one-day shortfall against the six-day reference.

## Z10 · Matching a practice hike to the trek

**User input**

My practice hike had the same duration as a day on the ABC trek, but we carried almost nothing and took a lift down. What information is still missing from my comparison?

**Retrieved fact IDs, in order**  KT-D5-E, KT-D3-E, KT-D4-E

**RAG answer · 0/2**

> The comparison is missing the specific **stage endpoint labels** and the **exact walking period** covered by the lift, as the provided records define elapsed time from the first to the last GPS fix for the full walking day and do not account for lift transfers or reduced loads.
>
> [KT-D5-E] "One publisher observation; individual travel times may differ. Stage endpoints are publisher labels."
>
> [KT-D3-E] "Elapsed time from the first GPS fix to the last fix for the walking day, including stops."
>
> [KT-D4-E] "Elapsed time from the first GPS fix to the last fix for the walking day, including stops."

**Baseline answer · 1/2**

> Based on the available information, the following details are missing from your comparison:
>
> *   **Exact ABC Corridor Reference:** The specific ABC itinerary or corridor (e.g., Everest Base Camp, Annapurna Circuit, Langtang) was not identified to match your hike's duration against official stage observations [N/A].
> *   **Recorded Stage Observations:** Without a specific corridor, there are no recorded stage observations, elevation profiles, or verified distances to confirm if your "almost nothing" load aligns with standard gear requirements for that route [N/A].
> *   **Lift Down Verification:** The specific issuer, exact trail section, and period of validity for the lift-down arrangement or the "lift down" condition were not provided [N/A].
> *   **Seasonal Context:** The seasonal context (e.g., monsoon, pre-monsoon) was not specified, which is required to verify if the conditions supported a "light load" strategy [N/A].
> *   **Equipment and Preparation Guidance:** Without the corridor and season, there is no verified equipment list or preparation guidance to confirm if your load was appropriate for the intended walking period [N/A].
>
> To complete the comparison, you must provide the specific ABC corridor name, the date of the hike (for seasonal context), and the official source or ID for the lift-down arrangement.

The retrieved timing records do not establish how pack weight or the omitted descent affect the training comparison. Citations to genuine facts did not make the advice responsive.

## Inspect the run

[All paired answers and retrieved IDs](r38/pair-results.json) · [Domain totals and release decision](r38/release-decision.json) · [Lookup guide for the cited facts](../documents/README.md)
