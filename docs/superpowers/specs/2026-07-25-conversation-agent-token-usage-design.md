# Conversation Agent Token Usage Design

## Status

Approved for implementation.

## Objective

Display the provider-reported token consumption for each completed user-to-Agent exchange in the conversational review workbench.

One exchange may contain several internal model turns because the Agent can call tools and then ask the model to continue. The UI must show one aggregate for the assistant message:

```text
输入 3,200 · 输出 480 · 总计 3,680 Token
```

## Scope

This change covers the conversational review Agent exposed through:

```text
POST /review-sessions/{session_id}/messages
```

It does not change formal `ReviewRun` cost reporting, FDE dashboards, model pricing, token budgets, or raw-vault capture.

## Existing Behavior

The conversation Agent already:

- receives a provider `usage` object after every model turn;
- stores the raw per-turn usage in `agent.model_call.completed` events;
- accumulates numeric raw usage fields across the exchange;
- returns that aggregate in `assistantMessage.execution.usage`;
- persists the assistant message and returns it through the message-history API.

The frontend already accepts a generic `execution.usage` object but does not render it.

The current raw accumulation is provider-shape-dependent. Providers may report equivalent values under names such as `prompt_tokens`/`completion_tokens` or `input_tokens`/`output_tokens`. Adding arbitrary raw keys can therefore produce an unstable API contract and can double count aliases.

## Design

### Backend normalization

Normalize each model turn with the existing `normalize_model_usage()` helper before aggregation.

For each turn, add these canonical counters to the exchange aggregate:

- `inputTokens`
- `outputTokens`
- `totalTokens`

The exchange aggregate is the sum of every actual model call belonging to the user request, including calls that request tools and the final answer call.

Preserve the existing raw per-turn `usage` inside `agent.model_call.completed` events for auditability. Only the assistant-message contract is normalized.

Return the canonical aggregate in:

```json
{
  "execution": {
    "usage": {
      "inputTokens": 3200,
      "outputTokens": 480,
      "totalTokens": 3680
    }
  }
}
```

Do not estimate missing provider usage. If no model call reports measurable usage, omit `execution.usage`.

If one or more model calls report usage and a later turn fails, include the accumulated usage in the `deterministic_fallback` execution result. Tokens already consumed must remain visible even when the Agent does not complete normally.

### API and TypeScript contract

Replace the frontend's generic `Record<string, number>` usage type with a dedicated optional token-usage type:

```ts
type ReviewBTokenUsage = {
  inputTokens: number
  outputTokens: number
  totalTokens: number
}
```

The field remains optional for backward compatibility with historical messages, deterministic commands, and providers that do not report usage.

### User interface

For assistant messages with measurable usage, render a subdued metadata line beneath the message content and existing execution label:

```text
输入 3,200 · 输出 480 · 总计 3,680 Token
```

Use locale-aware integer formatting. Do not render a token row for:

- user or system messages;
- deterministic commands that did not call a model;
- assistant messages without measurable provider usage.

Historical assistant messages using legacy snake_case keys may be supported by a small read-only compatibility normalizer in the component. New backend responses must always use canonical camelCase keys.

## Data Flow

1. The user posts a message.
2. The conversation Agent performs one or more model calls.
3. Each provider usage object is normalized and added to the exchange aggregate.
4. The aggregate is attached to the assistant message's `execution`.
5. The assistant message is persisted with the existing review-message record.
6. Both the POST response and subsequent history reads return the same usage.
7. The frontend formats and displays the three canonical counters.

No separate token-statistics endpoint or database collection is required.

## Error Handling

- Invalid, absent, or negative provider values normalize to zero.
- An all-zero aggregate is treated as unavailable and is not displayed.
- Partial usage survives a later Agent failure.
- Rendering must tolerate missing fields and legacy key names without producing `NaN`.

## Verification

Backend tests must cover:

- a single model turn;
- multiple tool-calling turns summed into one exchange;
- alias normalization for common provider usage shapes;
- partial usage returned after a later failure;
- no usage field when the provider reports none.

Frontend tests or focused component tests must cover:

- canonical input/output/total rendering;
- thousands separators;
- absence for deterministic or unmeasured messages;
- safe handling of historical snake_case usage.

Run the existing targeted backend conversation-Agent tests and frontend type checking after the changes.

## Acceptance Criteria

- Every newly persisted assistant message produced by the LLM conversation Agent contains one canonical exchange-level usage object when provider usage is available.
- The displayed values include all internal model turns for that user request.
- The values remain available after reloading message history.
- Failed exchanges show already-consumed tokens when available.
- The UI shows only input, output, and total Token counts and does not display estimates as measured usage.
