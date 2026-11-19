# Databricks notebook source
# MAGIC %md
# MAGIC # Travel Booking Analytics — Notebook 4: The Trip-Planner Agent
# MAGIC
# MAGIC A generic destination trip-planner. The user names any of the 42
# MAGIC wanderbricks destinations (a city or a country), a number of nights, and a
# MAGIC budget. The agent recommends real properties that fit the budget and
# MAGIC describes the destination.
# MAGIC
# MAGIC **This is the RAG piece of the learning exercise.** RAG = Retrieval-
# MAGIC Augmented Generation: retrieve relevant text first, then let the model
# MAGIC generate an answer grounded in it. Here the "documents" are the
# MAGIC destination description texts; one of the agent's tools is a RAG tool.
# MAGIC
# MAGIC **Honest scope:**
# MAGIC  - Works for the 42 wanderbricks destinations only. If the user names
# MAGIC    something else, the agent says so and lists what it can do.
# MAGIC  - No flights — Free Edition has no flight data and no outbound internet.
# MAGIC    The agent is upfront about this.
# MAGIC  - Managed Vector Search is not on Free Edition (confirmed in Notebook 0).
# MAGIC    The RAG retrieval here is done in-notebook by chunking and scoring the
# MAGIC    description text. In a company workspace, managed Vector Search does
# MAGIC    exactly this step — embeddings + similarity search — at scale.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Setup

# COMMAND ----------

MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"
print(f"Model: {MODEL_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load the destination data
# MAGIC
# MAGIC Two things are loaded once into plain Python: the destination list (for
# MAGIC resolving what the user asks for) and the description texts (the RAG
# MAGIC documents). 42 destinations is small — no managed index is needed.

# COMMAND ----------

# destination catalog: name + country, lower-cased keys for matching
dest_rows = spark.sql("""
    SELECT destination_id, destination, country
    FROM samples.wanderbricks.destinations
""").collect()

DEST_BY_CITY = {}      # 'paris' -> row
DEST_BY_COUNTRY = {}   # 'france' -> [rows]
for r in dest_rows:
    DEST_BY_CITY[r["destination"].lower()] = r
    DEST_BY_COUNTRY.setdefault(r["country"].lower(), []).append(r)

ALL_CITIES = sorted(r["destination"] for r in dest_rows)
print(f"Loaded {len(dest_rows)} destinations across {len(DEST_BY_COUNTRY)} countries.")
print("Destinations:", ", ".join(ALL_CITIES))

# COMMAND ----------

# description texts, keyed by destination_id (these are the RAG documents)
desc_rows = spark.sql("""
    SELECT destination_id, description
    FROM samples.wanderbricks.destinations
""").collect()
DESC_BY_ID = {r["destination_id"]: (r["description"] or "") for r in desc_rows}
print(f"Loaded {len(DESC_BY_ID)} destination descriptions.")
print(f"Example length (Paris-sized): {max(len(d) for d in DESC_BY_ID.values()):,} characters")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Resolve what the user asked for
# MAGIC
# MAGIC The user may name a city ('Paris') or a country ('Germany'). This
# MAGIC function turns their text into a concrete destination — or reports that
# MAGIC it is not one of the 42.

# COMMAND ----------

def resolve_destination(text: str):
    """Return (status, payload).
    status 'city'    -> payload is a single destination row
    status 'country' -> payload is a list of destination rows
    status 'unknown' -> payload is None
    """
    key = (text or "").strip().lower()
    if key in DEST_BY_CITY:
        return "city", DEST_BY_CITY[key]
    if key in DEST_BY_COUNTRY:
        return "country", DEST_BY_COUNTRY[key]
    # loose match: user typed something close
    for city in DEST_BY_CITY:
        if key and (key in city or city in key):
            return "city", DEST_BY_CITY[city]
    return "unknown", None

# quick test
for t in ["Paris", "germany", "Atlantis", "tokyo"]:
    status, payload = resolve_destination(t)
    if status == "city":
        print(f"  '{t}' -> city: {payload['destination']}, {payload['country']}")
    elif status == "country":
        print(f"  '{t}' -> country with {len(payload)} destinations")
    else:
        print(f"  '{t}' -> unknown")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. The Tools
# MAGIC
# MAGIC Three tools. The first is the RAG tool; the other two query structured
# MAGIC data and do arithmetic.

# COMMAND ----------

# --- TOOL 1: destination info (THE RAG TOOL) ---
# RAG step 1 (indexing): split the description into chunks, done once below.
# RAG step 2 (retrieval): score chunks against the question, return the best.

def _chunk(text: str):
    """Split a description into chunks. The text is Markdown with ## / ###
    headings, so split on headings — each section becomes one chunk."""
    import re
    parts = re.split(r'\n(?=#+ )', text)
    return [p.strip() for p in parts if len(p.strip()) > 40]

def tool_destination_info(dest_row, question: str) -> str:
    """RAG tool: retrieve the most relevant chunks of a destination's
    description for the question, and return them as grounding text."""
    full = DESC_BY_ID.get(dest_row["destination_id"], "")
    if not full:
        return f"(No description text available for {dest_row['destination']}.)"
    chunks = _chunk(full)
    # retrieval: score each chunk by word overlap with the question
    q_words = {w for w in question.lower().split() if len(w) > 3}
    scored = []
    for c in chunks:
        c_words = set(c.lower().split())
        score = len(q_words & c_words)
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    # take the top chunks; if nothing scored, fall back to the opening chunk
    top = [c for s, c in scored[:2] if s > 0] or [chunks[0]]
    retrieved = "\n\n".join(top)
    # keep it bounded — retrieval means NOT sending the whole 25k-char doc
    return retrieved[:1800]


# --- TOOL 2: property finder (structured query) ---
def tool_find_properties(dest_row, max_nightly_price: float, limit: int = 6) -> list:
    """Find properties at a destination within a nightly price ceiling."""
    rows = spark.sql(f"""
        SELECT title, property_type, base_price, bedrooms, max_guests
        FROM samples.wanderbricks.properties
        WHERE destination_id = {dest_row['destination_id']}
          AND base_price <= {float(max_nightly_price)}
        ORDER BY base_price ASC
        LIMIT {int(limit)}
    """).collect()
    return [dict(r.asDict()) for r in rows]


# --- TOOL 3: budget check (arithmetic) ---
def tool_budget_check(base_price: float, nights: int, budget: float) -> dict:
    """Estimate accommodation cost for a stay and compare to the budget."""
    est = round(float(base_price) * int(nights), 2)
    return {
        "nights": int(nights),
        "nightly_price": float(base_price),
        "estimated_accommodation": est,
        "budget": float(budget),
        "within_budget": est <= float(budget),
        "remaining": round(float(budget) - est, 2),
    }

print("Three tools defined: destination_info (RAG), find_properties, budget_check.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. The model client

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

ws = WorkspaceClient()

def ask_model(messages: list) -> str:
    role_map = {"system": ChatMessageRole.SYSTEM,
                "user": ChatMessageRole.USER,
                "assistant": ChatMessageRole.ASSISTANT}
    chat = [ChatMessage(role=role_map[m["role"]], content=m["content"])
            for m in messages]
    resp = ws.serving_endpoints.query(name=MODEL_ENDPOINT, messages=chat)
    return resp.choices[0].message.content

try:
    ask_model([{"role": "user", "content": "Reply with exactly: OK"}])
    MODEL_OK = True
    print("Model endpoint reachable.")
except Exception as e:
    MODEL_OK = False
    print(f"Model endpoint unreachable ({e}). The planner will still run and")
    print("show the structured plan; only the natural-language write-up is skipped.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. The Trip-Planner Agent
# MAGIC
# MAGIC The agent orchestrates the three tools:
# MAGIC  1. Resolve the destination (and handle 'not one of the 42' gracefully).
# MAGIC  2. find_properties — properties within budget per night.
# MAGIC  3. budget_check — confirm the numbers for each candidate.
# MAGIC  4. destination_info (RAG) — retrieve description text for context.
# MAGIC  5. The model writes the plan, grounded in the retrieved data.

# COMMAND ----------

def plan_trip(destination_text: str, nights: int, budget: float) -> str:
    print(f"REQUEST: {destination_text}, {nights} nights, budget {budget:.0f}\n")

    # --- Step 1: resolve the destination ---
    status, payload = resolve_destination(destination_text)
    if status == "unknown":
        return ("I can only plan for these 42 destinations:\n"
                + ", ".join(ALL_CITIES)
                + f"\n\n'{destination_text}' is not one of them.")
    if status == "country":
        cities = [r["destination"] for r in payload]
        if len(cities) > 1:
            return (f"{destination_text.title()} has several destinations in the "
                    f"data: {', '.join(cities)}. Please ask for one of them.")
        dest_row = payload[0]
    else:
        dest_row = payload
    print(f"  destination resolved: {dest_row['destination']}, {dest_row['country']}")

    # --- Step 2: budget per night, then find properties ---
    per_night_ceiling = float(budget) / int(nights)
    props = tool_find_properties(dest_row, per_night_ceiling, limit=6)
    print(f"  properties within {per_night_ceiling:.0f}/night: {len(props)} found")
    if not props:
        return (f"For {dest_row['destination']}, no properties fit a budget of "
                f"{budget:.0f} over {nights} nights "
                f"(about {per_night_ceiling:.0f}/night). Try more nights, a "
                f"higher budget, or a less expensive destination.")

    # --- Step 3: budget-check each candidate ---
    candidates = []
    for pr in props:
        chk = tool_budget_check(pr["base_price"], nights, budget)
        candidates.append({**pr, **chk})

    # --- Step 4: RAG — retrieve destination context ---
    rag_query = f"top tourist attractions and things to do in {dest_row['destination']}"
    context = tool_destination_info(dest_row, rag_query)
    print(f"  RAG retrieved {len(context)} characters of destination context")

    # --- Step 5: assemble the structured plan ---
    lines = [f"TRIP PLAN — {dest_row['destination']}, {dest_row['country']}",
             f"{nights} nights, budget {budget:.0f}", "",
             "Accommodation options within budget:"]
    for c in candidates:
        flag = "OK" if c["within_budget"] else "OVER"
        lines.append(f"  [{flag}] {c['title']}  ({c['property_type']}, "
                      f"{c['bedrooms']} bed) — {c['nightly_price']:.0f}/night "
                      f"x {nights} = {c['estimated_accommodation']:.0f}, "
                      f"leaves {c['remaining']:.0f}")
    structured = "\n".join(lines)

    # --- Step 6: the model writes the plan, grounded in retrieved data ---
    if MODEL_OK:
        try:
            answer = ask_model([
                {"role": "system",
                 "content": "You are a travel planner. Using ONLY the data "
                            "provided, write a friendly, concise trip plan "
                            "(about 5-8 sentences). Recommend ONE property and "
                            "say why. Use the destination context for a sentence "
                            "or two of colour. Do NOT invent prices, properties, "
                            "or flight information. If asked about flights, say "
                            "they are not included in this plan."},
                {"role": "user",
                 "content": f"Destination context (retrieved):\n{context}\n\n"
                            f"{structured}\n\n"
                            f"Write the trip plan. Accommodation only — no flights."},
            ])
            return (structured + "\n\n" + "-"*60 + "\nPLANNER:\n" + answer.strip()
                    + "\n\n(Note: flights are not included — no flight data on "
                      "this tier.)")
        except Exception as e:
            print(f"  (model write-up failed: {e})")
    return structured + "\n\n(Note: flights are not included.)"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Run the planner

# COMMAND ----------

print(plan_trip("Paris", nights=4, budget=1000))

# COMMAND ----------

print(plan_trip("Tokyo", nights=5, budget=1200))

# COMMAND ----------

# a destination that is not in the data — handled gracefully
print(plan_trip("Iceland", nights=3, budget=900))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Try your own
# MAGIC
# MAGIC Edit the destination, nights, and budget below. Any of the 42
# MAGIC destinations works — Phuket, Berlin, Rome, New York, Cairo, and so on.

# COMMAND ----------

print(plan_trip("Rome", nights=4, budget=1000))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. What this demonstrates
# MAGIC
# MAGIC **RAG, built correctly — as one tool inside an agent:**
# MAGIC  - The destination descriptions are the documents.
# MAGIC  - tool_destination_info does retrieval: it chunks a description and
# MAGIC    returns only the chunks relevant to the question — not the whole
# MAGIC    25,000-character text. That is the "retrieval" in RAG.
# MAGIC  - The model then generates the plan grounded in the retrieved text.
# MAGIC  - Retrieve, then generate — the RAG pattern.
# MAGIC
# MAGIC **Honest notes:**
# MAGIC  - Real RAG retrieval uses embeddings and vector similarity search.
# MAGIC    Managed Databricks Vector Search does this at scale; it is not on
# MAGIC    Free Edition, so retrieval here is done by in-notebook chunk scoring.
# MAGIC    The PATTERN is the same; the company-workspace version swaps in the
# MAGIC    managed index.
# MAGIC  - A trip planner is an AGENT that uses RAG as one tool — not a pure RAG
# MAGIC    app. Budgeting is arithmetic; property search is a structured query;
# MAGIC    only the destination-context step is RAG. Seeing which part is which
# MAGIC    is the architecture lesson.
# MAGIC  - Flights are out of scope: no flight data, no outbound internet on
# MAGIC    Free Edition. In a company build, a flights tool would call a real
# MAGIC    external API — another tool in the same agent.
