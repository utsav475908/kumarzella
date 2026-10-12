# AI coach

The coach answers questions about the trader's own journal, reviews single trades, suggests tags and summarises a day or a week. It runs on the operator's own API key, OpenAI (default model `gpt-5.5`), DeepSeek (default `deepseek-chat`) or Anthropic's Claude (default `claude-opus-5-5`).

Code:

- `backend/app/modules/ai/tools.py` defines the read-only tools the model can call.
- `backend/app/modules/ai/coach.py` runs the bounded tool loop and stores the result.
- `backend/app/modules/ai/grounding.py` is the unsupported-claim check.
- `backend/app/modules/ai/client.py` holds the Anthropic, OpenAI and DeepSeek clients and their error handling. The coach speaks the Anthropic Messages format, and `OpenAIClient` translates each request to OpenAI Chat Completions (tools become strict functions, tool results become `tool` messages, the answer schema becomes a strict `response_format`) and the reply back. `DeepSeekClient` reuses that translation with DeepSeek's narrower feature set: the `system` role, plain JSON mode (the answer schema is put in the system prompt), non-strict tools, no `reasoning_effort` and `max_tokens`. DeepSeek therefore doesn't guarantee the answer shape, so the evidence check matters more there. The loop, the evidence check and storage are the same for all three.
- `backend/app/modules/ai/router.py` exposes the API under `/api/v1/ai`.
- `frontend/src/pages/Coach.tsx` holds the Coach page and the trade page's AI review panel.
- `frontend/src/components/CoachAnswer.tsx` renders an answer with its citations and evidence.

## Turning it on

The coach is off until an API key is configured. When it is off, every coach endpoint returns `503 ai_not_configured` and nothing is sent anywhere.

- **Docker Compose:** create a file named `.env` next to `docker-compose.yml` (git ignores it) containing `OPENAI_API_KEY=sk-...`, `DEEPSEEK_API_KEY=sk-...` or `ANTHROPIC_API_KEY=sk-ant-...`. Then run `docker compose up -d`. Optional lines: `AI_PROVIDER=openai` or `AI_PROVIDER=deepseek` to pick one when several keys are present, `OPENAI_MODEL=...` and `DEEPSEEK_MODEL=...`.
- **Native:** set `EL_OPENAI_API_KEY`, `EL_DEEPSEEK_API_KEY` or `EL_ANTHROPIC_API_KEY`. The plain names also work.
- **Which provider:** `EL_AI_PROVIDER=auto` (the default) uses Anthropic when its key is set, then OpenAI, then DeepSeek.

Usage is billed to that key. Settings, all `EL_*`:

| Setting | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `auto` | `auto`, `openai`, `deepseek` or `anthropic` |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek model |
| `OPENAI_MODEL` | `gpt-5.5` | OpenAI model |
| `AI_MODEL` | `claude-opus-5-5` | Anthropic model |
| `AI_EFFORT` | `medium` | Thinking effort (OpenAI `reasoning_effort`): `low` to `max` |
| `AI_FALLBACKS` | `true` | Anthropic server-side refusal fallbacks (see below) |
| `AI_MAX_TOOL_ROUNDS` | 6 | Model calls that may request tools, per answer |
| `AI_MAX_TOOL_CALLS` | 16 | Tool runs per answer |
| `AI_TOKEN_BUDGET` | 250,000 | Input plus output tokens per answer, across all calls |
| `AI_MAX_TOKENS` | 8,000 | Output tokens per call |
| `AI_TIMEOUT_SECONDS` | 120 | Per HTTP request (the SDK retries twice) |
| `AI_RATE_LIMIT` / `AI_RATE_WINDOW_SECONDS` | 30 / 3600 | Coach requests per user per window |
| `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`, `DEEPSEEK_BASE_URL` | unset | Alternative API endpoints (tests point them at `tests/fake_claude.py`) |

## API

| Endpoint | What it does |
|---|---|
| `GET /ai/status` | Whether the coach is configured, the model, and the limits |
| `POST /ai/ask` `{question, filters?}` | Answers a question. `filters` passes the page's filters as context. |
| `POST /ai/trades/{id}/review` | Reviews one trade and suggests up to 3 tags |
| `POST /ai/summary` `{date_from, date_to}` | Summarises a day or a period of up to 92 days |
| `GET /ai/reviews?trade_id=&kind=` | Past answers, newest first |
| `GET /ai/reviews/{id}` | One answer with all of its evidence |
| `DELETE /ai/reviews/{id}` | Deletes an answer and its evidence |

Every answer comes back with:

- `answer`, with citations like `[E1]`.
- `evidence`: one entry per tool call. Each entry has the tool, its input, the filters applied, the sample size, and the exact result the model saw.
- `cited`: the evidence the answer refers to.
- `limitations`: sample size, excluded trades, missing data, plus anything the evidence check found.
- `status`: `ok`, `ungrounded`, `declined` or `incomplete`.
- `unsupported_numbers`: figures that could not be traced to the evidence.
- `usage`: tokens, model calls, tool calls, repairs and latency.

## How an answer is produced

1. The request goes to the model with a fixed system prompt (`coach.SYSTEM_PROMPT`), the eight tools below, and a JSON response schema. The system prompt and the tools never change between requests, so prompt caching applies.
2. While the model asks for tools, the server runs them as the signed-in user. Each result goes back labelled with an evidence ref (E1, E2 and so on). The loop is bounded by `AI_MAX_TOOL_ROUNDS`, `AI_MAX_TOOL_CALLS` and `AI_TOKEN_BUDGET`. On the last allowed round the model is told to answer with what it has.
3. The final answer goes through the [evidence check](#the-evidence-check). If it fails, the model is asked once to fix the answer. If the answer still fails, it is stored as `ungrounded`, and the page shows a red warning that lists the figures that could not be traced.
4. The answer and every tool result are stored in `ai_reviews` and `ai_evidence` (migration 0005). Both are included in the data export and are deleted with the user or the trade.

Model behaviour is pinned down on the server:

- **Thinking:** always on; depth is set with `effort`.
- **Tool choice:** `auto`. Every tool is `strict: true`.
- **Final answer:** must match the response schema (`output_config.format`).
- **Refusals (Anthropic):** when Claude declines a request, the API re-runs it on Anthropic's recommended fallback model inside the same call (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). If the whole chain declines, the answer is stored as `declined`.
- **API errors:** an invalid key, a rate limit or a network error becomes a clear `503 ai_unavailable` message.

## Tools

Every tool is read-only. Each one runs with the user id taken from the session, never from the model, and goes through the same user-scoped queries as the API.

| Tool | Returns | Built on |
|---|---|---|
| `performance_summary(filters, currency)` | Headline metrics plus breakdowns by direction, symbol, playbook, weekday, hour and session; costs, risk checks, last 31 days | `analytics.service.dashboard` |
| `strategy_report(filters, currency)` | Playbook comparison, rule adherence, results by tag, holding time and month; costs by symbol | `analytics.reports.report` |
| `list_trades(filters, sort, limit)` | Up to 25 trades, best or worst by net P&L or R, newest or oldest | `trades.filters`, `trades.service.to_out` |
| `get_trade(trade_id)` | One trade with fills, playbook rule checks, notes and day note | `trades.service.get_owned_trade`, `playbooks.service.assess_trades` |
| `period_summary(date_from, date_to)` | Metrics, P&L per day, trades and day notes for up to 92 days | `analytics.service.dashboard` |
| `search_journal(query, limit)` | Trade notes and day notes containing the text | journal tables |
| `tags_and_playbooks()` | The trader's tags (with usage counts) and playbooks | journal, playbooks |
| `metric_definitions(names)` | How each metric is defined | `analytics.definitions` |

Filters are: dates, symbols, direction, playbook name (or `none`), tag name, and outcome. A tool input the server can't use (a bad date, an unknown playbook name, another user's trade id) goes back to the model as an error result. The error lists only the trader's own names.

## The evidence check

`grounding.check` extracts every figure from the answer and its limitations. A figure counts as supported when, at the precision the answer shows, it equals a value in the evidence:

- `$2,728` matches `2728.40`.
- `75%` matches the ratio `0.7500`.
- `-2.02R` matches `-2.0200`.
- The sign is ignored, because "a loss of $202" quotes `-202`.
- Fields ending in `_seconds` also match in minutes and hours.

The check does not look at:

- Dates and times.
- Citation markers.
- List numbering.
- Years.
- Symbols such as `ESH4`.
- Bare counts from 0 to 10 (too ambiguous to check).
- Numbers the user wrote in their own question.

The check also flags citations of evidence that doesn't exist, and counts sentences that state a figure without citing anything.

The model is told never to calculate figures itself. A figure it worked out, even correctly, fails the check, because the analytics service didn't produce it.

## Untrusted text and prompt injection

- Trade notes, day notes and imported text reach the model only inside tool results, in fields named `untrusted_text`. Each such result carries a notice that the text is data.
- The system prompt tells the model never to follow instructions found in those fields.
- Even a model that followed such an instruction could do nothing with it:
  - No tool writes, places orders or changes settings.
  - An unknown tool name returns an error.
  - Every tool is scoped to the signed-in user.
  - Any figure the injected text tricks the model into stating fails the evidence check.
- Tag suggestions are only suggestions. A tag is added to a trade only when the trader clicks the button.

## What is sent to the AI provider

- The question.
- The system prompt.
- The tool results the model asks for. These can include trade figures, symbols, prices, tag and playbook names, and note text.

Nothing else is sent: no email, password, session, API keys or other users' data. The server logs only ids, status, counts, tokens and latency, never the question, the answer or the evidence. With the coach off, nothing is sent.

## Tests

`backend/tests/test_ai_coach.py` runs against a scripted model (`FakeModel`) and never calls the network:

- **Numerical accuracy:** figures in an answer are compared with the analytics endpoints and with the hand-computed fixture (net 260.45, 75% win rate, profit factor 2.2894, short net -81.20, daily P&L).
- **Evidence coverage:** an answer is checked for its cited refs and evidence entries, and for citations of evidence that doesn't exist.
- **Unsupported claims:** a made-up figure triggers one repair round and is then flagged. A repaired answer is accepted. A table of extraction and matching cases covers the check itself.
- **Authorization:**
  - The coach tools can't read another user's trades. `get_trade` with a foreign id returns an error, and `list_trades` returns nothing.
  - The review endpoints return 404 across users.
  - Listing is scoped.
- **Prompt injection:** a note tells the model to place orders, delete trades and claim a 99% win rate. The test checks that:
  - the note reaches the model only as `untrusted_text`;
  - the fake tools fail as unknown;
  - no trade changes;
  - the 99% is flagged.
- **Budgets:** a model that never stops calling tools is cut off at the round and tool-call limits. The token budget stops the loop. Coach requests are rate-limited.
- **Refusal:** a declined request is stored as `declined`.
- **Real SDK paths:** the actual Anthropic, OpenAI and DeepSeek clients run against `tests/fake_claude.py`, a scripted local HTTP server. The Anthropic test checks the beta header, `fallbacks: "default"`, the API key header, the effort setting and the message order. The OpenAI test checks the translated request: `developer`, `user`, `assistant` (with `tool_calls`) and `tool` messages, strict functions, the strict response format and `reasoning_effort`. The DeepSeek test checks JSON mode, the `system` role and the absence of strict tools and `reasoning_effort`. Provider selection from the keys is tested too.

`frontend/src/pages/coach.test.tsx` covers:

- the setup message when the coach is off;
- asking a question, then opening a citation's evidence;
- the warning for figures that could not be traced;
- adding suggested tags, which happens only on click.

`frontend/e2e/coach.spec.ts` runs the whole path in a browser: register, import, ask, and open the evidence. It then reviews a trade, reloads the page and checks the review is still shown. CI runs it against the scripted server. Without a key, it checks the setup message instead.

## Limitations

- Each question is answered on its own. A follow-up doesn't see the earlier answer; ask with the context included.
- The coach reads the journal, reports and playbooks. It does not read backtest sessions or candles.
- The evidence check is about numbers. It can't tell whether a sentence's reasoning is sound. Read each answer as a set of candidate patterns to check.
- Answers take several seconds, because each tool round is another model call. The page shows progress.
- Live answers depend on the operator's OpenAI, DeepSeek or Anthropic account: its rate limits, its model access and its cost.
- DeepSeek support has only been tested against the scripted server, not a live account. The model name `deepseek-chat` is a default; set `DEEPSEEK_MODEL` if your account uses another.
