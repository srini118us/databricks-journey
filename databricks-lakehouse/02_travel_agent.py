# Databricks notebook source
# MAGIC %md
# MAGIC # Travel Booking Analytics — Notebook 2: the Agent
# MAGIC
# MAGIC **Use case:** a tool-calling **agent** that answers travel-business questions
# MAGIC in plain English by querying the gold tables built in Notebook 1.
# MAGIC
# MAGIC **What an agent is.** An ordinary program follows fixed steps. An agent is
# MAGIC given a goal and a set of *tools*, and it decides which tool to use. Here the
# MAGIC tools are Python functions that query the gold tables. You ask a question;
# MAGIC the language model reads it, picks the right tool, the tool runs real SQL,
# MAGIC and the model turns the result into a plain-English answer.
# MAGIC
# MAGIC **The loop:**  question -> model picks a tool -> tool queries gold -> model answers
# MAGIC
# MAGIC Run top to bottom. Prerequisite: Notebook 1 has been run (the gold tables exist).

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Setup

# COMMAND ----------

CATALOG = "workspace"
SCHEMA  = "travel_analytics"
spark.sql(f"USE {CATALOG}.{SCHEMA}")

# The language model the agent reasons with.
# Confirmed working on Free Edition. To swap, change this one line —
# e.g. "databricks-llama-4-maverick" or "databricks-gpt-oss-120b".
MODEL_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

print(f"Schema : {CATALOG}.{SCHEMA}")
print(f"Model  : {MODEL_ENDPOINT}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. The Tools
# MAGIC
# MAGIC Each tool is a plain Python function that queries one gold table and returns
# MAGIC a small text result. These are the *only* things the agent can do — its
# MAGIC capabilities are exactly this list. Note every tool reads the **gold** layer,
# MAGIC never raw data: the serving-layer principle from Day 1.

# COMMAND ----------

def tool_top_destinations(limit: int = 5) -> str:
    """Top destinations by total revenue. Use for 'best/top destinations',
    'where do we earn most', 'most popular places'."""
    rows = spark.sql(f"""
        SELECT destination, country, total_bookings, total_revenue, avg_booking_value
        FROM gold_revenue_by_destination
        ORDER BY total_revenue DESC
        LIMIT {int(limit)}
    """).collect()
    lines = [f"{r['destination']} ({r['country']}): "
             f"revenue ${r['total_revenue']:,.0f}, "
             f"{r['total_bookings']:,} bookings, "
             f"avg ${r['avg_booking_value']:,.0f}" for r in rows]
    return "Top destinations by revenue:\n" + "\n".join(lines)


def tool_monthly_trend(months: int = 6) -> str:
    """Recent monthly revenue trend. Use for 'trend', 'how is revenue over time',
    'recent months', 'is business growing'."""
    rows = spark.sql(f"""
        SELECT booking_month, total_bookings, total_revenue
        FROM gold_monthly_revenue
        ORDER BY booking_month DESC
        LIMIT {int(months)}
    """).collect()
    rows = list(reversed(rows))
    lines = [f"{str(r['booking_month'])[:7]}: "
             f"${r['total_revenue']:,.0f} from {r['total_bookings']:,} bookings"
             for r in rows]
    return "Monthly revenue trend (most recent):\n" + "\n".join(lines)


def tool_revenue_by_property_type() -> str:
    """Revenue split by property type. Use for 'property type', 'what kind of
    property earns most', 'house vs apartment vs hotel'."""
    rows = spark.sql("""
        SELECT property_type, total_bookings, total_revenue, avg_booking_value
        FROM gold_revenue_by_property_type
        ORDER BY total_revenue DESC
    """).collect()
    lines = [f"{r['property_type']}: revenue ${r['total_revenue']:,.0f}, "
             f"{r['total_bookings']:,} bookings, avg ${r['avg_booking_value']:,.0f}"
             for r in rows]
    return "Revenue by property type:\n" + "\n".join(lines)


def tool_payment_methods() -> str:
    """Breakdown of completed payments by method. Use for 'payment methods',
    'how do customers pay', 'credit card vs paypal'."""
    rows = spark.sql("""
        SELECT payment_method, payment_count, total_paid
        FROM gold_payment_methods
        ORDER BY total_paid DESC
    """).collect()
    lines = [f"{r['payment_method']}: ${r['total_paid']:,.0f} "
             f"across {r['payment_count']:,} payments" for r in rows]
    return "Payment methods (completed payments):\n" + "\n".join(lines)


# The tool registry: name -> (function, description for the model)
TOOLS = {
    "top_destinations": (
        tool_top_destinations,
        "Top destinations by total revenue. Args: limit (int, default 5)."),
    "monthly_trend": (
        tool_monthly_trend,
        "Recent monthly revenue trend. Args: months (int, default 6)."),
    "revenue_by_property_type": (
        tool_revenue_by_property_type,
        "Revenue split by property type. No args."),
    "payment_methods": (
        tool_payment_methods,
        "Completed payments broken down by payment method. No args."),
}

# quick self-test — tools work on their own, before any model is involved
print("Tool self-test:\n")
print(tool_top_destinations(3))
print()
print(tool_revenue_by_property_type())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. The model client
# MAGIC
# MAGIC The agent talks to the language model through the Databricks SDK, which
# MAGIC calls the model-serving endpoint (governed by the AI Gateway).

# COMMAND ----------

from databricks.sdk import WorkspaceClient

ws = WorkspaceClient()

def ask_model(messages: list) -> str:
    """Send a chat conversation to the model endpoint, return the text reply."""
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
    chat = []
    for m in messages:
        role = {"system": ChatMessageRole.SYSTEM,
                "user": ChatMessageRole.USER,
                "assistant": ChatMessageRole.ASSISTANT}[m["role"]]
        chat.append(ChatMessage(role=role, content=m["content"]))
    resp = ws.serving_endpoints.query(name=MODEL_ENDPOINT, messages=chat)
    return resp.choices[0].message.content

# connectivity test
try:
    reply = ask_model([{"role": "user", "content": "Reply with exactly: OK"}])
    print(f"Model endpoint reachable. Reply: {reply.strip()[:60]}")
    MODEL_OK = True
except Exception as e:
    print(f"Model endpoint NOT reachable from notebook code:\n  {e}")
    print("\nThe agent will fall back to a keyword router so the tool-calling")
    print("loop still works without the model.")
    MODEL_OK = False

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. The agent loop
# MAGIC
# MAGIC The agent works in two steps:
# MAGIC  1. **Route** — given the question and the tool list, decide which tool to call.
# MAGIC  2. **Answer** — run that tool, then have the model phrase the result as a
# MAGIC     natural answer.
# MAGIC
# MAGIC If the model endpoint is unreachable, a simple keyword router stands in for
# MAGIC step 1, so the agent still demonstrates the tool-calling loop.

# COMMAND ----------

import json

TOOL_LIST_TEXT = "\n".join(f"- {name}: {desc}" for name, (_, desc) in TOOLS.items())

def route_with_model(question: str) -> dict:
    """Ask the model which tool to use. Returns {'tool':..., 'args':{...}}."""
    system = (
        "You are a routing component for a travel-analytics agent. "
        "Given the user question, choose exactly ONE tool from this list:\n"
        f"{TOOL_LIST_TEXT}\n\n"
        "Respond with ONLY a JSON object, no other text, of the form "
        '{\"tool\": \"<tool_name>\", \"args\": {}}. '
        "Include numeric args only if the user implies a specific count."
    )
    raw = ask_model([{"role": "system", "content": system},
                     {"role": "user", "content": question}])
    raw = raw.strip()
    if "{" in raw:
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
    return json.loads(raw)

def route_with_keywords(question: str) -> dict:
    """Fallback router: pick a tool by keyword matching."""
    q = question.lower()
    if any(w in q for w in ["trend", "month", "over time", "growing", "growth"]):
        return {"tool": "monthly_trend", "args": {}}
    if any(w in q for w in ["property type", "kind of property", "house",
                            "apartment", "hotel", "ski", "type"]):
        return {"tool": "revenue_by_property_type", "args": {}}
    if any(w in q for w in ["payment", "pay", "credit card", "paypal"]):
        return {"tool": "payment_methods", "args": {}}
    return {"tool": "top_destinations", "args": {}}

def run_agent(question: str) -> str:
    print(f"USER: {question}")

    # Step 1 — route to a tool
    try:
        decision = route_with_model(question) if MODEL_OK else route_with_keywords(question)
    except Exception as e:
        print(f"  (model routing failed: {e}; using keyword router)")
        decision = route_with_keywords(question)

    tool_name = decision.get("tool")
    args = decision.get("args", {}) or {}
    if tool_name not in TOOLS:
        return f"AGENT: I don't have a tool for that. Available: {', '.join(TOOLS)}"
    print(f"  -> agent chose tool: {tool_name}({args})")

    # Step 2 — run the tool
    fn = TOOLS[tool_name][0]
    try:
        tool_result = fn(**args)
    except TypeError:
        tool_result = fn()  # ignore bad args, call with defaults
    print(f"  -> tool returned data ({len(tool_result.splitlines())} lines)")

    # Step 3 — phrase the answer
    if MODEL_OK:
        try:
            answer = ask_model([
                {"role": "system",
                 "content": "You are a travel-business analyst. Using ONLY the "
                            "data provided, answer the user's question clearly "
                            "in 2-4 sentences. Do not invent numbers."},
                {"role": "user",
                 "content": f"Question: {question}\n\nData:\n{tool_result}"},
            ])
            return f"AGENT: {answer.strip()}"
        except Exception as e:
            print(f"  (model answering failed: {e}; returning raw tool data)")
    return f"AGENT (raw tool data):\n{tool_result}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Ask the agent

# COMMAND ----------

print(run_agent("Which destinations make us the most money?"))
print("\n" + "-"*70 + "\n")
print(run_agent("How has revenue been trending recently?"))

# COMMAND ----------

print(run_agent("What kind of property earns the most?"))
print("\n" + "-"*70 + "\n")
print(run_agent("How do our customers usually pay?"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Try your own question
# MAGIC
# MAGIC Edit the question below and re-run. Try things like:
# MAGIC  - "What are the top 3 destinations?"
# MAGIC  - "Is the business growing?"
# MAGIC  - "Compare property types for me."

# COMMAND ----------

print(run_agent("What are our top 3 destinations by revenue?"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. What this demonstrates — and where MCP and guardrails fit
# MAGIC
# MAGIC **Built end to end:**
# MAGIC  - a medallion ETL on real travel data (Notebook 1)
# MAGIC  - gold analytics tables (Notebook 1)
# MAGIC  - a tool-calling agent: question -> model routes -> tool queries gold -> model answers
# MAGIC
# MAGIC **Where the remaining AI-Gateway features would slot in (company-workspace):**
# MAGIC  - **Guardrails** — the AI Gateway can enforce input/output safety rules on
# MAGIC    every model call. Here that would screen the question and the answer.
# MAGIC  - **MCP** — the Model Context Protocol is a standard way to expose these
# MAGIC    tools so *any* MCP-aware agent could use them, not just this notebook.
# MAGIC    The Gateway's "MCPs" tab governs those connections.
# MAGIC  - **Rate limits / usage tracking** — every call above already passes through
# MAGIC    the AI Gateway, which is where an org sets limits and monitors cost.
# MAGIC
# MAGIC On Free Edition the agent runs here in the notebook; deploying it as a served
# MAGIC endpoint with MCP and live guardrails is a company-workspace step.
