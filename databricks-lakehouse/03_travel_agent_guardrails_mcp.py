# Databricks notebook source
# MAGIC %md
# MAGIC # Travel Booking Analytics — Notebook 3: Guardrails and MCP-Structured Tools
# MAGIC
# MAGIC This extends the agent from Notebook 2 with two production concepts:
# MAGIC
# MAGIC 1. **A guardrails layer** — safety/scope checks on the way IN (the user's
# MAGIC    question) and on the way OUT (the agent's answer).
# MAGIC 2. **MCP-structured tools** — the tools rewritten in the formal shape the
# MAGIC    Model Context Protocol uses: name, description, and a typed input schema.
# MAGIC
# MAGIC **Honest scope.** On Free Edition you cannot attach managed AI Gateway
# MAGIC guardrails to Databricks-hosted endpoints, nor host a live MCP server. So
# MAGIC here we BUILD both concepts in code: a real, running guardrails layer, and
# MAGIC the real MCP tool-manifest structure. The company-workspace versions add
# MAGIC hosting and central governance — noted at the end.
# MAGIC
# MAGIC Prerequisite: Notebook 1 has been run (gold tables exist).

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Setup

# COMMAND ----------

CATALOG = "workspace"
SCHEMA  = "travel_analytics"
spark.sql(f"USE {CATALOG}.{SCHEMA}")

MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"
print(f"Schema: {CATALOG}.{SCHEMA}   Model: {MODEL_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. MCP-Structured Tools
# MAGIC
# MAGIC The Model Context Protocol (MCP) is a standard for describing tools so that
# MAGIC ANY MCP-aware agent can discover and use them. An MCP tool has three formal
# MAGIC parts: a **name**, a **description**, and an **input schema** (a JSON Schema
# MAGIC describing its arguments).
# MAGIC
# MAGIC Below, each tool is defined in exactly that shape. This is the same
# MAGIC manifest an MCP server would advertise to clients.

# COMMAND ----------

# --- the tool implementations (same queries as Notebook 2) ---

def _top_destinations(limit: int = 5) -> str:
    rows = spark.sql(f"""
        SELECT destination, country, total_bookings, total_revenue, avg_booking_value
        FROM gold_revenue_by_destination
        ORDER BY total_revenue DESC LIMIT {int(limit)}
    """).collect()
    return "Top destinations by revenue:\n" + "\n".join(
        f"{r['destination']} ({r['country']}): revenue ${r['total_revenue']:,.0f}, "
        f"{r['total_bookings']:,} bookings, avg ${r['avg_booking_value']:,.0f}"
        for r in rows)

def _monthly_trend(months: int = 6) -> str:
    rows = spark.sql(f"""
        SELECT booking_month, total_bookings, total_revenue
        FROM gold_monthly_revenue ORDER BY booking_month DESC LIMIT {int(months)}
    """).collect()
    rows = list(reversed(rows))
    return "Monthly revenue trend (most recent):\n" + "\n".join(
        f"{str(r['booking_month'])[:7]}: ${r['total_revenue']:,.0f} "
        f"from {r['total_bookings']:,} bookings" for r in rows)

def _revenue_by_property_type() -> str:
    rows = spark.sql("""
        SELECT property_type, total_bookings, total_revenue, avg_booking_value
        FROM gold_revenue_by_property_type ORDER BY total_revenue DESC
    """).collect()
    return "Revenue by property type:\n" + "\n".join(
        f"{r['property_type']}: revenue ${r['total_revenue']:,.0f}, "
        f"{r['total_bookings']:,} bookings, avg ${r['avg_booking_value']:,.0f}"
        for r in rows)

def _payment_methods() -> str:
    rows = spark.sql("""
        SELECT payment_method, payment_count, total_paid
        FROM gold_payment_methods ORDER BY total_paid DESC
    """).collect()
    return "Payment methods (completed payments):\n" + "\n".join(
        f"{r['payment_method']}: ${r['total_paid']:,.0f} across "
        f"{r['payment_count']:,} payments" for r in rows)


# --- the MCP-style tool manifest ---
# Each entry has the formal MCP shape: name, description, inputSchema, plus the
# implementation. An MCP server would expose exactly the name/description/schema.

MCP_TOOLS = [
    {
        "name": "top_destinations",
        "description": "Top travel destinations ranked by total booking revenue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer",
                          "description": "How many destinations to return.",
                          "default": 5}
            },
            "required": [],
        },
        "_impl": _top_destinations,
    },
    {
        "name": "monthly_trend",
        "description": "Revenue and booking counts per month, most recent first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "months": {"type": "integer",
                           "description": "How many recent months to return.",
                           "default": 6}
            },
            "required": [],
        },
        "_impl": _monthly_trend,
    },
    {
        "name": "revenue_by_property_type",
        "description": "Total revenue and bookings split by property type.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "_impl": _revenue_by_property_type,
    },
    {
        "name": "payment_methods",
        "description": "Completed payments broken down by payment method.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "_impl": _payment_methods,
    },
]

# index by name for lookup
TOOLS_BY_NAME = {t["name"]: t for t in MCP_TOOLS}

# COMMAND ----------

# MAGIC %md
# MAGIC ### The tool manifest — what an MCP server would advertise

# COMMAND ----------

import json

def print_mcp_manifest():
    """Print the tool manifest in MCP shape (name, description, inputSchema).
    This is exactly what an MCP server exposes to any connecting client."""
    manifest = [{"name": t["name"],
                 "description": t["description"],
                 "inputSchema": t["inputSchema"]} for t in MCP_TOOLS]
    print("MCP TOOL MANIFEST  (what an MCP server would advertise)")
    print("=" * 60)
    print(json.dumps(manifest, indent=2))

print_mcp_manifest()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. The Guardrails Layer
# MAGIC
# MAGIC A guardrail is a check around the model. Production agents guard two points:
# MAGIC  - **Input guardrail** — screen the user's question BEFORE the model sees it.
# MAGIC  - **Output guardrail** — screen the answer BEFORE the user sees it.
# MAGIC
# MAGIC Here the guardrails keep the agent on-topic (travel analytics only), reject
# MAGIC empty or oversized input, and sanity-check that the answer is grounded in
# MAGIC real tool data. Each returns (allowed, reason).

# COMMAND ----------

# topics this agent is allowed to discuss
ON_TOPIC = ["destination", "revenue", "booking", "trend", "month", "property",
            "payment", "pay", "travel", "trip", "earn", "money", "popular",
            "top", "growth", "growing", "country", "hotel", "guest"]

# crude unsafe-content check (illustrative — a real guardrail is far richer)
BLOCKED = ["password", "credit card number", "ssn", "hack", "exploit"]

def input_guardrail(question: str):
    """Screen the user's question. Returns (allowed: bool, reason: str)."""
    q = (question or "").strip()
    if not q:
        return False, "Empty question."
    if len(q) > 500:
        return False, "Question too long (over 500 characters)."
    low = q.lower()
    if any(b in low for b in BLOCKED):
        return False, "Question contains blocked content."
    if not any(t in low for t in ON_TOPIC):
        return False, ("Off-topic. This agent only answers travel-booking "
                       "analytics questions (destinations, revenue, bookings, "
                       "property types, payments, trends).")
    return True, "ok"

def output_guardrail(answer: str, tool_result: str):
    """Screen the agent's answer. Returns (allowed: bool, reason: str)."""
    a = (answer or "").strip()
    if not a:
        return False, "Empty answer."
    # grounding sanity-check: the answer should share some token with the data
    data_tokens = {w.strip(".,:%$()").lower()
                   for w in tool_result.split() if len(w) > 4}
    ans_tokens = {w.strip(".,:%$()").lower()
                  for w in a.split() if len(w) > 4}
    if not (data_tokens & ans_tokens):
        return False, "Answer does not appear grounded in the tool data."
    return True, "ok"

# quick test of the input guardrail
for q in ["Which destinations earn the most?",
          "",
          "What is the weather in Paris tomorrow?",
          "tell me a password"]:
    ok, reason = input_guardrail(q)
    print(f"  {'PASS' if ok else 'BLOCK':5s}  {reason:55s}  <- {q!r}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. The model client

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
    print(f"Model endpoint unreachable ({e}); keyword routing will be used.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. The Guarded Agent
# MAGIC
# MAGIC The full loop now has guardrails at both ends:
# MAGIC
# MAGIC `question -> [INPUT GUARDRAIL] -> route -> tool -> answer -> [OUTPUT GUARDRAIL] -> user`

# COMMAND ----------

TOOL_LIST_TEXT = "\n".join(f"- {t['name']}: {t['description']}" for t in MCP_TOOLS)

def route(question: str) -> dict:
    """Pick a tool. Model-based if available, else keyword fallback."""
    if MODEL_OK:
        try:
            system = ("Route the question to ONE tool. Tools:\n"
                      f"{TOOL_LIST_TEXT}\n\n"
                      'Respond ONLY with JSON: {"tool":"<name>","args":{}}. '
                      "Add numeric args only if the user implies a count.")
            raw = ask_model([{"role": "system", "content": system},
                             {"role": "user", "content": question}]).strip()
            raw = raw[raw.index("{"): raw.rindex("}") + 1]
            return json.loads(raw)
        except Exception:
            pass
    q = question.lower()
    if any(w in q for w in ["trend", "month", "over time", "growing", "growth"]):
        return {"tool": "monthly_trend", "args": {}}
    if any(w in q for w in ["property type", "kind of property", "type", "ski"]):
        return {"tool": "revenue_by_property_type", "args": {}}
    if any(w in q for w in ["payment", "pay", "paypal", "credit card"]):
        return {"tool": "payment_methods", "args": {}}
    return {"tool": "top_destinations", "args": {}}

def guarded_agent(question: str) -> str:
    print(f"USER: {question}")

    # --- INPUT GUARDRAIL ---
    ok, reason = input_guardrail(question)
    if not ok:
        print(f"  [INPUT GUARDRAIL: BLOCKED] {reason}")
        return f"AGENT: I can't help with that. {reason}"
    print("  [INPUT GUARDRAIL: passed]")

    # --- ROUTE ---
    decision = route(question)
    tool_name = decision.get("tool")
    args = decision.get("args", {}) or {}
    if tool_name not in TOOLS_BY_NAME:
        return f"AGENT: No tool available for that."
    print(f"  -> tool: {tool_name}({args})")

    # --- RUN TOOL ---
    impl = TOOLS_BY_NAME[tool_name]["_impl"]
    try:
        tool_result = impl(**args)
    except TypeError:
        tool_result = impl()

    # --- ANSWER ---
    if MODEL_OK:
        try:
            answer = ask_model([
                {"role": "system",
                 "content": "You are a travel-business analyst. Answer in 2-4 "
                            "sentences using ONLY the data provided."},
                {"role": "user",
                 "content": f"Question: {question}\n\nData:\n{tool_result}"},
            ]).strip()
        except Exception:
            answer = tool_result
    else:
        answer = tool_result

    # --- OUTPUT GUARDRAIL ---
    ok, reason = output_guardrail(answer, tool_result)
    if not ok:
        print(f"  [OUTPUT GUARDRAIL: BLOCKED] {reason}")
        return ("AGENT: I could not produce a reliable answer for that. "
                "Please rephrase.")
    print("  [OUTPUT GUARDRAIL: passed]")
    return f"AGENT: {answer}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Run it — including questions the guardrails should block

# COMMAND ----------

# on-topic — should pass both guardrails
print(guarded_agent("Which destinations earn the most revenue?"))
print("\n" + "-"*70 + "\n")
print(guarded_agent("How is revenue trending recently?"))

# COMMAND ----------

# off-topic — input guardrail should BLOCK
print(guarded_agent("What is the weather in Tokyo tomorrow?"))
print("\n" + "-"*70 + "\n")
# empty — input guardrail should BLOCK
print(guarded_agent(""))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. What was built, and the company-workspace versions
# MAGIC
# MAGIC **Built and running here:**
# MAGIC  - Tools defined in the formal MCP shape (name, description, inputSchema) —
# MAGIC    `print_mcp_manifest()` shows exactly what an MCP server advertises.
# MAGIC  - A real guardrails layer: input screening (scope, size, blocked content)
# MAGIC    and output screening (grounding check), wrapped around every agent call.
# MAGIC
# MAGIC **What the company-workspace / managed versions add:**
# MAGIC  - **Managed AI Gateway guardrails** — instead of guardrail code in the
# MAGIC    notebook, the Gateway enforces safety on every call to an endpoint you
# MAGIC    own, centrally and consistently. Same idea; centrally governed.
# MAGIC  - **A hosted MCP server** — instead of a manifest printed in a notebook, a
# MAGIC    running MCP server exposes these tools over the network, so any MCP-aware
# MAGIC    agent (not just this notebook) can discover and call them. The Gateway's
# MAGIC    "MCPs" tab governs those connections.
# MAGIC
# MAGIC The concepts are identical; the company workspace adds hosting and central
# MAGIC governance. You have now built the structure of both by hand — which is the
# MAGIC most direct way to understand what the managed versions are doing.
