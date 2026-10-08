# QuickMove Vendor Message Extractor — Architecture & Flow

Ops staff paste a vendor message (WhatsApp, email) or a screenshot. The app turns it into a structured, reviewable record, flags risks, suggests the next action, and saves it to a local SQLite DB that can be filtered and exported to CSV.

## High-level architecture

```
                    streamlit_app.py  (UI: input → review → saved records)
                       │            │
              extract()│            │ insert / all_records / export_csv
                       ▼            ▼
              app/extractor.py    app/store.py ──► records.db (SQLite)
              (orchestrator)
        ┌──────────┼───────────────┐
        ▼          ▼               ▼
 app/jev_client  app/claude_client  app/ollama_client
 (TypeSafe Jev:  (Anthropic Claude: (local Ollama:
  enums, flags,   text + vision +    text only,
  confidence)     action sentence)   same interface)
        ▲          ▲               ▲
        └──────────┴── app/prompts.py (all prompts + Jev questions)

 app/schema.py (VendorRecord, pydantic) is the shared data shape used by everything.
```

Two engines cooperate on the text path:
- **Jev (TypeSafe)** — good at classification: message type, vendor category, red-flag probabilities, confidence. Cannot return free text.
- **LLM (Ollama or Claude)** — fills the free-text fields (vendor name, amount, dates, inclusions, contact, etc.) and writes the action sentence.

The LLM backend is chosen by env var `LLM_BACKEND`: `ollama` (default, local, text only) or `claude` (needs `ANTHROPIC_API_KEY`, adds screenshot support).

## Flow

### Text message
1. User pastes text and clicks **Extract** in `streamlit_app.py`.
2. `extractor.extract(message, None)` → `extract_with_jev(message)`:
   1. `regex_hints()` pulls candidate amounts, phones, emails, dates (Indian formats: `Rs`, `₹`, `45k`, `1.2L`, `DD-MM-YYYY`, `12 Nov`).
   2. `jev_client.t()` asks Jev the questions in `JEV_QUESTIONS` → `message_type`, `vendor_category`, and 0–1 probabilities for each red flag.
   3. The LLM's `fill_text_fields(message, hints)` returns the free-text JSON.
   4. Jev flags with probability ≥ `FLAG_THRESHOLD` (0.85) become red-flag text. `no_gst` / `low_price` are only kept for quotes. They are merged with LLM-found flags and deduplicated case-insensitively.
   5. Confidence = the lower of Jev's two classification confidences, bucketed into high (≥0.8), medium (≥0.5) or low.
3. The result is validated into a `VendorRecord`.
4. The LLM's `write_action_sentence()` adds a one-line "what to do next".

### Screenshot
`extract(message, image_bytes)` skips Jev. `claude_client.extract_with_vision()` reads the image (plus optional pasted text) and returns every field itself. Ollama raises a clear error here because it has no vision.

### Review and save
The UI shows the record with a confidence chip and red-flag chips. Every field is editable. **Save record** rebuilds a `VendorRecord` from the widgets and calls `store.insert()`.

### Browse and export
The "Saved records" section filters by category, type and saved date via `store.all_records()`. A row click shows its full JSON, and **Download CSV** calls `store.export_csv()`.

## Files

### Application
| File | Purpose |
|---|---|
| `streamlit_app.py` | The whole UI. Section 1 takes input (text or image) and runs extraction. Section 2 is an editable review form (selectboxes, data editor for dates, line-per-item text areas for lists). Section 3 lists saved records with filters, detail view and CSV download. Uses `st.session_state` to hold the current record; a `run` counter is baked into widget keys so a new extraction resets the form. |
| `app/extractor.py` | Orchestrator. Picks the LLM backend (`_llm()`), builds regex hints, combines Jev + LLM output, applies the flag threshold and confidence mapping, and produces the final `VendorRecord`. Has an inline `__main__` self-check for the regexes. |
| `app/jev_client.py` | Thin wrapper over the TypeSafe SDK (`typesafe_sdk`). `t(message, schema)` converts the question dict into Choice/Noul/Score objects and returns a flat `{name: value}` dict (plus `{name}_confidence` for choice/score). Isolates SDK changes to one file. |
| `app/claude_client.py` | Anthropic Claude backend: `fill_text_fields`, `extract_with_vision` (base64 image + optional text), `write_action_sentence`. Also holds `_ask` (lazy client, appends today's date to the system prompt) and `_json` (extracts the JSON object from the reply, tolerating code fences or extra prose). |
| `app/ollama_client.py` | Local Ollama backend with the same three functions as the Claude client. Calls `/api/chat` with temperature 0 and forces JSON mode for JSON prompts. Configurable via `OLLAMA_MODEL` (default `qwen2.5:14b`) and `OLLAMA_URL`. Vision raises `RuntimeError`. Reuses `_json` from the Claude client. |
| `app/prompts.py` | All prompt text: shared `CONTEXT` (Indian relocation domain rules, Hinglish, date and currency normalization, category mapping, red-flag guidance), `TEXT_FILL_SYSTEM`, `VISION_SYSTEM`, `ACTION_SYSTEM`, plus `JEV_QUESTIONS` (the two choice questions) and `JEV_FLAGS` (noul question → red-flag text, which also generates the noul entries in `JEV_QUESTIONS`). |
| `app/schema.py` | Pydantic models: `VendorRecord` (the core record), `Amount`, `DateItem`, `Contact`, and the allowed values for message type, vendor category and confidence. A validator turns `null` lists from the LLM into `[]`. |
| `app/store.py` | SQLite persistence (`records.db`, path overridable with `RECORDS_DB`). `init_db`, `insert`, `all_records(filters)` and `export_csv`. List and object fields are stored as JSON strings and decoded on read. A small `_conn()` context manager commits and closes. Has an inline self-check. |
| `app/__init__.py` | Empty; makes `app` a package. |

### Config
| File | Purpose |
|---|---|
| `.env.example` | Template for env vars: `TYPESAFE_API_KEY`, `LLM_BACKEND`, `ANTHROPIC_API_KEY`. Copy to `.env`. |
| `.streamlit/config.toml` | Streamlit theme (teal on light), minimal toolbar, usage stats off. |
| `requirements.txt` | Pinned Python dependencies. |
| `.gitignore` | Keeps `.env`, `records.db` and the like out of git. |

### Tests and samples
| File | Purpose |
|---|---|
| `tests/test_app.py` | `unittest` suite with mocked Jev and LLM. It covers schema, regex hints, extraction merge logic, the Claude client, the SQLite store, and the Streamlit UI. `TempDB` gives each test a throwaway database. |
| `tests/__init__.py` | Empty package marker. |
| `sample_messages/01…06_*.txt` | Made-up vendor messages for manual testing: packers quote, mover delay (Hinglish), utility confirmation, broker listing, Hinglish cancellation, and an ambiguous status that should come back low confidence. |
| `sample_messages/README.md` | Table of what each sample exercises. |
| `README.md` | Project overview and setup. |

## Configuration summary
| Env var | Effect |
|---|---|
| `LLM_BACKEND` | `ollama` (default) or `claude` |
| `ANTHROPIC_API_KEY` | Needed for the `claude` backend |
| `TYPESAFE_API_KEY` | Needed for Jev (text path) |
| `OLLAMA_MODEL` / `OLLAMA_URL` | Ollama model and server |
| `RECORDS_DB` | Override the SQLite file path |

## Design notes
- **Swappable backends:** both LLM clients expose the same three functions, so `extractor.py` never cares which is active.
- **Jev for the "judgement", LLM for the "text":** high-confidence enum and flag decisions come from Jev; the LLM never decides category or type on the text path.
- **Human in the loop:** nothing is saved until ops reviews and edits the extracted record.
