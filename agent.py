"""
Browser Automation Agent - simulates page navigation, tab inspection,
form filling, and result submission for mini web-app workflows.

Primary  : Uses Claude API with observation->action loop (plan → observe → act → validate).
Fallback : Direct data extraction from page state when API is unavailable.

Input  : test_inputs.json  [{id, task, initial_page, pages}, ...]
Output : results.json      [{id, output: {invoice_id, note_submitted, action_trace}}, ...]
"""

import json, os, re, sys, textwrap
from pathlib import Path

MODEL         = os.getenv("ANTHROPIC_MODEL",   "claude-3-5-haiku-20241022")
MAX_TOKENS    = 1024
INPUT_FILE    = Path(os.getenv("INPUT_FILE",   "test_inputs.json"))
OUTPUT_FILE   = Path(os.getenv("OUTPUT_FILE",  "results.json"))
DATASET_FILE  = Path(os.getenv("DATASET_FILE", "dataset.json"))

# ---------------------------------------------------------------------------
# System prompt for the browser agent
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = textwrap.dedent("""
    You are a browser automation agent. You are given a simulated web-app state
    with pages, UI elements, and embedded data. Your job is to navigate through
    the page states to complete the task.

    For each step, you MUST:
    1. OBSERVE the current page: list its elements and available data.
    2. DECIDE the next action based only on what you can see (no hallucination).
    3. ACT: choose one action from: navigate(page_id), click(element), fill(element, value), read(field).
    4. STOP when the task is complete and you have all required output values.

    Required output fields (return raw JSON only, no markdown):
    {
      "invoice_id":     "<invoice ID found in the invoices page data>",
      "note_submitted": true,
      "action_trace":   [
        {"step": 1, "page": "<page_id>", "action": "<action>", "detail": "<what you did/found>"},
        ...
      ]
    }

    Rules:
    - Only reference elements that exist in the current page's elements list.
    - If an element is missing, skip it and note it in the trace as "element_not_found".
    - Stop after submitting the note. Do not loop endlessly.
    - Never invent page data — only use what is provided in the page state.
""").strip()


def build_prompt(task: str, pages: list) -> str:
    """Builds the user prompt from the task and full page map."""
    page_descriptions = []
    for p in pages:
        page_descriptions.append(
            f"Page '{p['id']}':\n"
            f"  Elements: {p['elements']}\n"
            f"  Data: {json.dumps(p['data'])}"
        )
    page_map = "\n\n".join(page_descriptions)
    return (
        f"Task: {task}\n\n"
        f"Available pages (you start at the initial_page, navigate in order):\n\n"
        f"{page_map}\n\n"
        "Execute the full workflow and return the JSON output."
    )


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------
def call_claude(task: str, pages: list) -> dict:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic not installed")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_prompt(task, pages)}],
    )
    raw = msg.content[0].text.strip()
    # Strip accidental markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    parsed = json.loads(raw)
    if "invoice_id" not in parsed or "note_submitted" not in parsed:
        raise ValueError(f"Missing required keys in response: {parsed.keys()}")
    return parsed


# ---------------------------------------------------------------------------
# Fallback: deterministic browser simulation (no LLM needed)
# ---------------------------------------------------------------------------
def simulate_browser(task: str, initial_page: str, pages: list) -> dict:
    """
    Walks through the page graph deterministically, mimicking the agent loop:
    observe → decide → act.
    Returns the same output schema as call_claude().
    """
    page_index = {p["id"]: p for p in pages}
    trace = []
    step = 0
    invoice_id = None
    note_submitted = False

    def log(page_id, action, detail):
        nonlocal step
        step += 1
        trace.append({"step": step, "page": page_id, "action": action, "detail": detail})

    # --- Step 1: Navigate to initial page and search ---
    current = page_index.get(initial_page)
    if not current:
        log(initial_page, "navigate", f"ERROR: page '{initial_page}' not found — aborting")
        return {"invoice_id": None, "note_submitted": False, "action_trace": trace}

    log(current["id"], "navigate", f"Arrived at '{current['id']}'. Elements: {current['elements']}")

    query = current["data"].get("query", "")
    if "search_input" in current["elements"]:
        log(current["id"], "fill(search_input)", f"Typed search query: '{query}'")
    else:
        log(current["id"], "element_not_found", "search_input missing — skipping fill")

    if "search_button" in current["elements"]:
        log(current["id"], "click(search_button)", "Submitted search")
    else:
        log(current["id"], "element_not_found", "search_button missing — proceeding anyway")

    # --- Step 2: Navigate to customer_profile ---
    current = page_index.get("customer_profile")
    if not current:
        log("customer_profile", "navigate", "ERROR: customer_profile page missing")
        return {"invoice_id": None, "note_submitted": False, "action_trace": trace}

    log(current["id"], "navigate", f"Loaded customer profile. Customer: {current['data'].get('customer', 'unknown')}")

    # --- Step 3: Click invoices tab ---
    if "invoices_tab" in current["elements"]:
        log(current["id"], "click(invoices_tab)", "Opened Invoices tab")
    else:
        log(current["id"], "element_not_found", "invoices_tab not present — attempting direct navigation")

    # --- Step 4: Read invoices page ---
    current = page_index.get("invoices")
    if not current:
        log("invoices", "navigate", "ERROR: invoices page missing")
        return {"invoice_id": None, "note_submitted": False, "action_trace": trace}

    log(current["id"], "navigate", f"Invoices page loaded. Elements: {current['elements']}")

    if "invoice_rows" in current["elements"]:
        invoice_id = current["data"].get("overdue_invoice")
        amount = current["data"].get("amount", "unknown")
        if invoice_id:
            log(current["id"], "read(invoice_rows)", f"Found overdue invoice: {invoice_id}, amount: {amount}")
        else:
            log(current["id"], "read(invoice_rows)", "No overdue_invoice field in data — recording null")
    else:
        log(current["id"], "element_not_found", "invoice_rows element missing — cannot extract invoice")

    # --- Step 5: Navigate back to profile, click notes tab ---
    profile = page_index.get("customer_profile")
    if profile and "notes_tab" in profile["elements"]:
        log(profile["id"], "click(notes_tab)", "Navigated back to profile; clicked Notes tab")
    else:
        log("customer_profile", "navigate", "Navigating to notes page directly")

    # --- Step 6: Fill and submit note ---
    current = page_index.get("notes")
    if not current:
        log("notes", "navigate", "ERROR: notes page missing — cannot submit note")
        return {"invoice_id": invoice_id, "note_submitted": False, "action_trace": trace}

    log(current["id"], "navigate", "Notes page loaded")

    note_text = (
        f"Follow-up: Overdue invoice {invoice_id} requires immediate attention. "
        f"Please arrange payment at the earliest."
    ) if invoice_id else "Follow-up note: please review overdue invoices."

    if "note_textarea" in current["elements"]:
        log(current["id"], "fill(note_textarea)", f"Typed note: \"{note_text}\"")
    else:
        log(current["id"], "element_not_found", "note_textarea missing — skipping fill")

    if "submit_button" in current["elements"]:
        log(current["id"], "click(submit_button)", "Note submitted successfully")
        note_submitted = True
    else:
        log(current["id"], "element_not_found", "submit_button missing — note NOT submitted")

    # --- Step 7: Validate ---
    log(current["id"], "validate", (
        f"Workflow complete. invoice_id={invoice_id}, note_submitted={note_submitted}"
    ))

    return {
        "invoice_id":     invoice_id,
        "note_submitted": note_submitted,
        "action_trace":   trace,
    }


# ---------------------------------------------------------------------------
# Process one item
# ---------------------------------------------------------------------------
def process_item(item: dict, dataset_index: dict) -> dict:
    item_id      = item["id"]
    task         = item.get("task", "")
    initial_page = item.get("initial_page", "")
    pages        = item.get("pages", [])

    # Enrich pages from dataset if extra data is available
    ds_entry = dataset_index.get(item_id, {})
    if ds_entry.get("pages"):
        ds_pages = {p["id"]: p for p in ds_entry["pages"]}
        for pg in pages:
            if pg["id"] in ds_pages and not pg.get("data"):
                pg["data"] = ds_pages[pg["id"]].get("data", {})

    print(f"  [{item_id}] {task[:60]}...", end=" ", flush=True)

    result = None

    # Primary: Claude API with observation-action loop
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            result = call_claude(task, pages)
            # Ensure action_trace exists
            if "action_trace" not in result:
                result["action_trace"] = []
            print(f"API OK | invoice={result.get('invoice_id')} note={result.get('note_submitted')}")
        except Exception as exc:
            print(f"API FAIL ({type(exc).__name__}: {exc}) -> fallback")

    # Fallback: deterministic simulation
    if result is None:
        result = simulate_browser(task, initial_page, pages)
        print(f"SIM OK | invoice={result.get('invoice_id')} note={result.get('note_submitted')}")

    return {
        "id": item_id,
        "output": {
            "invoice_id":     result.get("invoice_id"),
            "note_submitted": result.get("note_submitted", False),
            "action_trace":   result.get("action_trace", []),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE, encoding="utf-8") as f:
        test_inputs = json.load(f)

    # Load dataset for enrichment
    dataset_index = {}
    if DATASET_FILE.exists():
        with open(DATASET_FILE, encoding="utf-8") as f:
            raw_ds = json.load(f)
        if isinstance(raw_ds, list):
            dataset_index = {r["id"]: r for r in raw_ds}

    api = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f"Browser Agent  model={MODEL}  api={'yes' if api else 'no (simulation mode)'}")
    print(f"Dataset index : {len(dataset_index)} entries")
    print(f"Processing    : {len(test_inputs)} tasks\n")

    results = [process_item(item, dataset_index) for item in test_inputs]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    ok = sum(1 for r in results if r["output"]["note_submitted"])
    print(f"\nDone. {ok}/{len(results)} tasks completed with note submitted.")
    print(f"Results -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
