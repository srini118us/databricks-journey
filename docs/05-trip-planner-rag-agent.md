# Use Case 5 — Trip-Planner RAG Agent + Natural-Language Chat

**Purpose.** A generic destination trip-planner that uses retrieval (RAG) to
recommend real properties within budget, fronted by a plain-English chat loop.
Contrasts English-to-agent (this) with Genie's English-to-SQL (Use Case 3).

**Dataset.** The 42 `wanderbricks` destinations and property data.

## Files

- `databricks-lakehouse/04_trip_planner_explore.py` — Step 0: enumerates
  destinations/countries/property counts; checks whether managed Vector Search is
  available (it is not on Free Edition -> decision to do in-notebook RAG).
- `databricks-lakehouse/05_trip_planner_agent.py` — the planner: resolves the
  user's city/country, retrieves destination description chunks in-notebook
  (embedding/similarity substitute for Vector Search), recommends real properties
  within budget. `plan_trip(dest, nights, budget)`.
- `databricks-lakehouse/06_trip_planner_chat.py` — a natural-language front door:
  an LLM parses a plain-English sentence into (destination, nights, budget) and
  calls the planner. Self-contained in-notebook chat loop.

## Outputs

A working RAG trip-planner and an NL chat interface over it.

## Notes

Vector Search is gated on Free Edition, so retrieval is done in-notebook — the
architecture lesson (retrieve-then-generate) still holds. Minor: the markdown
"Notebook N" numbers inside `05_`/`06_` don't line up with the file numbers; no
functional issue.
