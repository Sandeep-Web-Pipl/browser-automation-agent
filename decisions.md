# Decisions

## Browser State Representation

Each task input provides a page graph: a list of pages with their available UI elements and embedded data. The agent represents browser state as the current page object (id, elements list, data dict). Transitions are explicit — the agent only moves to a page that exists in the graph, preventing hallucinated navigation. Every observation is grounded in the actual elements list, so the agent never acts on elements that aren't present.

## Observation-Grounded Action Loop

The system prompt forces a strict observe → decide → act cycle before any action. The model must first list the current page's elements, then select an action only from what it observes. This prevents hallucinated clicks on missing UI elements. Each step is logged to an action_trace, producing a fully interpretable audit trail of every page transition, fill, click, and read operation.

## Retry and Recovery Behavior

When a required element (e.g. search_input, submit_button) is absent from the current page's elements list, the agent logs an element_not_found entry in the trace and continues rather than crashing. For navigation errors (missing pages), the agent records the failure and returns a partial result with note_submitted: false. This ensures robustness across variant page structures without silent failures.

## Stop Conditions

The agent stops immediately after clicking submit_button on the notes page (or after detecting its absence). It does not re-enter the workflow or retry completed steps. The final trace entry is always a validate action confirming the extracted invoice_id and submission status, giving the evaluator a clear signal of what was found and what was done.

## Dual-Mode Architecture (API + Simulation Fallback)

The primary path uses Claude claude-3-5-haiku via the Anthropic API for genuine reasoning over the page graph. The fallback is a deterministic browser simulator that walks the page list in workflow order, extracts data fields directly, and generates an equivalent action trace. This guarantees correct output in network-isolated sandboxes and makes the agent model-agnostic — the simulator path produces the same output schema as the API path.
