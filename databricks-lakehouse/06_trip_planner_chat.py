# Databricks notebook source
# MAGIC %md
# MAGIC # Travel Booking Analytics — Notebook 6: Chat Front Door for the Trip-Planner
# MAGIC
# MAGIC The trip-planner agent (Notebook 5) works, but you call it by editing
# MAGIC `plan_trip("Rome", 4, 1000)` in a cell. This notebook adds a **natural-
# MAGIC language front door**: the user types one plain-English sentence, a model
# MAGIC extracts the destination, nights, and budget from it, and the trip-planner
# MAGIC agent runs.
# MAGIC
# MAGIC `user message -> model parses it -> plan_trip(agent) -> trip plan`
# MAGIC
# MAGIC **The architecture point.** Genie is a natural-language interface for
# MAGIC QUERYING data (English to SQL). This is a natural-language interface for
# MAGIC running a TASK (English to an agent call). Same plain-English feel for the
# MAGIC user; different machinery underneath.
# MAGIC
# MAGIC **Honest scope.** This is a chat loop INSIDE the notebook. A deployed chat
# MAGIC app with a hosted prompt box is a company-workspace step (Model Serving /
# MAGIC Databricks Apps, tier-limited on Free Edition). What is built here is the
# MAGIC real natural-language-to-agent flow, minus the hosting.
# MAGIC
# MAGIC This notebook is self-contained — it rebuilds the planner pieces it needs,
# MAGIC so it can run on its own.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Setup and the planner (condensed from Notebook 5)

# COMMAND ----------

MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

# --- destination catalog ---
dest_rows = spark.sql("""
    SELECT destination_id, destination, country FROM samples.wanderbricks.destinations
""").collect()
DEST_BY_CITY = {r["destination"].lower(): r for r in dest_rows}
DEST_BY_COUNTRY = {}
for r in dest_rows:
    DEST_BY_COUNTRY.setdefault(r["country"].lower(), []).append(r)
ALL_CITIES = sorted(r["destination"] for r in dest_rows)

# --- description texts (RAG documents) ---
DESC_BY_ID = {r["destination_id"]: (r["description"] or "")
              for r in spark.sql("SELECT destination_id, description "
                                 "FROM samples.wanderbricks.destinations").collect()}

print(f"Loaded {len(dest_rows)} destinations.")

# COMMAND ----------

import re
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

ws = WorkspaceClient()

def ask_model(messages: list) -> str:
    role_map = {"system": ChatMessageRole.SYSTEM, "user": ChatMessageRole.USER,
                "assistant": ChatMessageRole.ASSISTANT}
    chat = [ChatMessage(role=role_map[m["role"]], content=m["content"]) for m in messages]
    return ws.serving_endpoints.query(name=MODEL_ENDPOINT, messages=chat).choices[0].message.content

try:
    ask_model([{"role": "user", "content": "Reply with exactly: OK"}])
    MODEL_OK = True
    print("Model endpoint reachable.")
except Exception as e:
    MODEL_OK = False
    print(f"Model endpoint unreachable: {e}")

# COMMAND ----------

# --- the planner tools and agent (condensed from Notebook 5) ---

def resolve_destination(text: str):
    key = (text or "").strip().lower()
    if key in DEST_BY_CITY:
        return "city", DEST_BY_CITY[key]
    if key in DEST_BY_COUNTRY:
        return "country", DEST_BY_COUNTRY[key]
    for city in DEST_BY_CITY:
        if key and (key in city or city in key):
            return "city", DEST_BY_CITY[city]
    return "unknown", None

def _chunk(text):
    return [p.strip() for p in re.split(r'\n(?=#+ )', text) if len(p.strip()) > 40]

def tool_destination_info(dest_row, question):
    full = DESC_BY_ID.get(dest_row["destination_id"], "")
    if not full:
        return ""
    chunks = _chunk(full)
    q_words = {w for w in question.lower().split() if len(w) > 3}
    scored = sorted(((len(q_words & set(c.lower().split())), c) for c in chunks),
                    key=lambda x: x[0], reverse=True)
    top = [c for s, c in scored[:2] if s > 0] or [chunks[0]]
    return "\n\n".join(top)[:1800]

def tool_find_properties(dest_row, max_nightly_price, limit=6):
    rows = spark.sql(f"""
        SELECT title, property_type, base_price, bedrooms, max_guests
        FROM samples.wanderbricks.properties
        WHERE destination_id = {dest_row['destination_id']}
          AND base_price <= {float(max_nightly_price)}
        ORDER BY base_price ASC LIMIT {int(limit)}
    """).collect()
    return [dict(r.asDict()) for r in rows]

def plan_trip(destination_text, nights, budget):
    status, payload = resolve_destination(destination_text)
    if status == "unknown":
        return ("I can only plan for these 42 destinations: "
                + ", ".join(ALL_CITIES) + f". '{destination_text}' is not one of them.")
    if status == "country":
        cities = [r["destination"] for r in payload]
        if len(cities) > 1:
            return (f"{destination_text.title()} has several destinations: "
                    f"{', '.join(cities)}. Please ask for one of them.")
        dest_row = payload[0]
    else:
        dest_row = payload

    per_night = float(budget) / int(nights)
    props = tool_find_properties(dest_row, per_night, limit=6)
    if not props:
        return (f"For {dest_row['destination']}, no properties fit {budget:.0f} "
                f"over {nights} nights (~{per_night:.0f}/night). Try more nights "
                f"or a higher budget.")

    cand = []
    for pr in props:
        est = round(pr["base_price"] * nights, 2)
        cand.append({**pr, "est": est, "remaining": round(budget - est, 2),
                     "ok": est <= budget})

    context = tool_destination_info(
        dest_row, f"top attractions and things to do in {dest_row['destination']}")

    lines = [f"TRIP PLAN — {dest_row['destination']}, {dest_row['country']}",
             f"{nights} nights, budget {budget:.0f}", "",
             "Accommodation options within budget:"]
    for c in cand:
        lines.append(f"  [{'OK' if c['ok'] else 'OVER'}] {c['title']} "
                      f"({c['property_type']}, {c['bedrooms']} bed) — "
                      f"{c['base_price']:.0f}/night x {nights} = {c['est']:.0f}, "
                      f"leaves {c['remaining']:.0f}")
    structured = "\n".join(lines)

    if MODEL_OK:
        try:
            answer = ask_model([
                {"role": "system",
                 "content": "You are a travel planner. Using ONLY the data given, "
                            "write a friendly 5-8 sentence plan. Recommend ONE "
                            "property and say why. Use the destination context for "
                            "colour. Never invent prices or flights; if asked about "
                            "flights, say they are not included."},
                {"role": "user",
                 "content": f"Destination context:\n{context}\n\n{structured}\n\n"
                            f"Write the plan. Accommodation only — no flights."},
            ])
            return structured + "\n\n" + "-"*60 + "\nPLANNER:\n" + answer.strip()
        except Exception:
            pass
    return structured

print("Planner ready.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The natural-language parser
# MAGIC
# MAGIC This is the new piece. It takes one free-text message and uses the model
# MAGIC to extract three things: destination, nights, budget. The model is told to
# MAGIC reply with strict JSON so the result can be used directly.

# COMMAND ----------

import json

def parse_request(message: str) -> dict:
    """Extract destination, nights, budget from a free-text message.
    Returns a dict; any value the user did not give comes back as null."""
    system = (
        "Extract trip details from the user's message. Respond with ONLY a JSON "
        "object, no other text:\n"
        '{"destination": <city or country, or null>, '
        '"nights": <integer number of nights, or null>, '
        '"budget": <number, the budget amount, or null>}\n'
        "If the user gives days, nights = days. If a value is not mentioned, "
        "use null. Do not guess a destination that was not named."
    )
    raw = ask_model([{"role": "system", "content": system},
                     {"role": "user", "content": message}]).strip()
    if "{" in raw:
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
    return json.loads(raw)

# test the parser
for m in ["I want to go to Paris for 4 days with about 2000 euros",
          "plan 5 nights in Tokyo, budget 1500",
          "somewhere in Italy for a week"]:
    print(f"  {m!r}\n    -> {parse_request(m)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. The chat front door
# MAGIC
# MAGIC This ties it together. The user sends one message. The parser extracts the
# MAGIC details. If anything essential is missing, the agent asks for it (instead
# MAGIC of guessing). When all three are known, it calls the trip-planner.

# COMMAND ----------

def chat_plan_trip(message: str) -> str:
    """Natural-language front door: a plain-English message in, a trip plan out."""
    print(f"USER: {message}")

    # --- parse the free text ---
    try:
        parsed = parse_request(message)
    except Exception as e:
        return f"ASSISTANT: Sorry, I couldn't understand that ({e}). Try e.g. " \
               f"'4 days in Paris with a budget of 2000 euros'."
    print(f"  parsed: {parsed}")

    destination = parsed.get("destination")
    nights = parsed.get("nights")
    budget = parsed.get("budget")

    # --- ask for anything missing, instead of guessing ---
    missing = []
    if not destination:
        missing.append("which destination")
    if not nights:
        missing.append("how many nights")
    if not budget:
        missing.append("your budget")
    if missing:
        return ("ASSISTANT: I can plan that — I just need " +
                ", and ".join(missing) +
                ". For example: '4 nights in Paris with a budget of 2000 euros'.")

    # --- all three known: run the planner agent ---
    print(f"  -> calling plan_trip({destination!r}, {nights}, {budget})")
    plan = plan_trip(destination, int(nights), float(budget))
    return "ASSISTANT:\n" + plan + \
           "\n\n(Flights are not included — no flight data on this tier.)"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Use it — like a chat

# COMMAND ----------

print(chat_plan_trip("I want to go to Paris for 4 days with about 2000 euros"))

# COMMAND ----------

print(chat_plan_trip("plan 5 nights in Tokyo, budget 1500"))

# COMMAND ----------

# a message missing the budget — the assistant should ASK, not guess
print(chat_plan_trip("I'd like to visit Rome for 3 days"))

# COMMAND ----------

# a destination not in the data — handled gracefully
print(chat_plan_trip("4 nights in Reykjavik, budget 2000"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Your turn — type into the input box
# MAGIC
# MAGIC The cell below creates a text input box at the TOP of this notebook
# MAGIC (a Databricks "widget"). Instead of editing code:
# MAGIC  1. Run the cell below once — an input box appears at the top of the page.
# MAGIC  2. Type your trip request into that box, in plain English, for example:
# MAGIC     `plan a trip to Paris for 4 days with a budget of 2000 euros`
# MAGIC  3. Run the cell after it to get your plan.
# MAGIC  4. To ask again, just change the text in the box and re-run that cell.

# COMMAND ----------

# create the input box (a text widget) at the top of the notebook
dbutils.widgets.text("trip_request",
                     "plan a trip to Paris for 4 days with a budget of 2000 euros",
                     "Your trip request")
print("Input box 'Your trip request' is now at the top of the notebook.")
print("Type your request there, then run the next cell.")

# COMMAND ----------

# this cell reads whatever you typed in the box above and plans the trip
my_request = dbutils.widgets.get("trip_request")
print(chat_plan_trip(my_request))

# COMMAND ----------

# MAGIC %md
# MAGIC To remove the input box later, run: `dbutils.widgets.remove("trip_request")`
# MAGIC — or `dbutils.widgets.removeAll()` to clear all widgets.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. What this demonstrates
# MAGIC
# MAGIC **The full natural-language-to-agent flow:**
# MAGIC  - The user writes one plain-English sentence.
# MAGIC  - A model parses it into structured fields (destination, nights, budget).
# MAGIC  - If something is missing, the assistant asks — it does not guess.
# MAGIC  - When the request is complete, the trip-planner agent runs.
# MAGIC
# MAGIC **The architecture lesson — two kinds of natural-language interface:**
# MAGIC  - Genie: natural language for QUERYING data — English becomes SQL.
# MAGIC  - This: natural language for running a TASK — English becomes an agent
# MAGIC    call. The parser is the bridge from free text to a structured call.
# MAGIC  - Same plain-English feel for the user; different machinery. Trip
# MAGIC    planning is a task, so it needs the agent, not Genie.
# MAGIC
# MAGIC **Honest note — the deployed version:**
# MAGIC  - This runs as a chat loop in the notebook. A real product would deploy
# MAGIC    the agent behind a hosted chat box (Model Serving or a Databricks App),
# MAGIC    so end users get a prompt without opening a notebook. That deployment
# MAGIC    is the company-workspace step; the logic here is exactly what would sit
# MAGIC    behind it.
