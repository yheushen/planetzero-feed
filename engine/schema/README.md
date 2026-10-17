# The feed contract

The engine writes these files; the web page, the connector (shot 3) and the audit (shot 3) read them. Nothing reads the sources directly. The schema files here are the contract: `build_feed.py` checks every file against them before writing it, and `evals/feed` (F1) checks the fixtures and every built feed.

## The 1 rule

A number never travels alone. Every reading carries its **unit**, **scale**, **band**, **window** (this hour, or the past 24 hours), **source**, **source type** (government monitor, community sensor, computer model, satellite), the **time it was measured**, the **station** it came from and a **credit** line. That is invariant 1 of `CLAUDE.md`, made into data.

## Files

| File | What | Schema |
|---|---|---|
| `now.json` | Every place: the hour, the 24-hour index, the other sensors within 10 km, the computer model's estimate; and what each source did on this run | `now.schema.json` |
| `outlook.json` | The next 5 days per place on the PSI scale, from CAMS, and the scorecard | `outlook.schema.json` |
| `grid.json` | The globe: smoke (1 degree), wind (1 degree near us, 5 degrees across the hemisphere), fires of the last 24 hours | `grid.schema.json` |
| `checks.json` | Our check results on numbers we may not republish (Google, IQAir); empty until shot 2 | `checks.schema.json` |
| `earth.json`, `earth/` | Earth's layers. The `real_earth` layer may carry `day_picture`: Real Earth as 1 finished picture a day, `earth/real/<date>-2048.webp` and `-4096.webp` with JPEG fallbacks, its gaps filled, its poles completed and its joins softened by the engine (parts 114 and 116); example in `fixtures/day_picture.json`. Without it the page builds the picture from GIBS | `earth.schema.json` |
| `earth/smoke/adjusted.json` | The hour's smoke model adjusted to the monitors near it (part 125), on the grid of the smoke layer's now file; named by the smoke layer's `adjusted`. An estimate, never an hour; history, downloads and the connector keep the model. Example in `fixtures/adjusted.json` | `adjusted.schema.json` |
| `scales.json` | The bands, colours and advice (SPEC section 6), shared by engine, page and connector | (data, not a schema) |

Shared pieces live in `common.schema.json`.

## A reading has 1 of 3 states

- `ok`: a number, fully labelled.
- `missing`: the source was asked and did not answer. The reason and the time we asked. Never an old value instead (invariant 10).
- `none`: there is no such number here, for example a Malaysian place with no open sensor within 10 km. Never invented (invariant 3).

`lead` says which number is the big one: `hour` exactly when the hour is `ok`, else `index`. The schema enforces it.

## Times

Local time in Malaysia and Singapore, with its offset: `2026-10-15T04:00+08:00`. An hourly reading's time is the end of its hour.

## Fixtures

`fixtures/` holds a replay of 15 October 2026, 4:12 am, for Central Singapore and Cheras, derived by hand from the answers recorded that morning (`engine/tests/recorded/`). `now.json` there carries `replay_of`, so the page says it is a replay.

## Changing the contract

Change the schema first, then the fixtures, then the engine and the page, and say so in `docs/DECISIONS.md`. `schema_version` goes up when an old reader would misread a new file.
