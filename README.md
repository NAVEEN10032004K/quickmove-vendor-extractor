# QuickMove Vendor Message Extractor

Ops people at QuickMove (relocation, 8 Indian cities) spend their day on unstructured vendor messages: packer quotes, utility confirmations, mover delay notices, broker listings, arriving as WhatsApp text, screenshots and forwarded emails. This tool turns each one into a structured record. Paste text or drop a screenshot, review and edit the extraction, save it to a local SQLite DB, and export everything as CSV. It's built for the 5-person ops team that currently re-keys all of this into a Google Sheet.

**Screenshot:** _(add later)_  
**Live link:** _(add after deploy)_

## Run with Docker (no Python setup needed)

You need Docker and a TypeSafe key (Jev), plus one LLM backend (see [Choosing the LLM backend](#choosing-the-llm-backend)).

```bash
printf 'TYPESAFE_API_KEY=your-key\nANTHROPIC_API_KEY=your-key\n' > .env

# Option A: pull the published image
docker run -d --name quickmove -p 8501:8501 --env-file .env -e LLM_BACKEND=claude -v quickmove-data:/data \
  <DOCKERHUB_USER>/quickmove-vendor-extractor:latest        # image ID / digest: <ADD AFTER PUSH>

# Option B: build it yourself (reference build: image ID 1df2baa94f5a, ~832 MB)
docker build -t quickmove-vendor-extractor .
docker run -d --name quickmove -p 8501:8501 --env-file .env -e LLM_BACKEND=claude -v quickmove-data:/data quickmove-vendor-extractor
```

To use a local Ollama on the host instead of Claude, replace `-e LLM_BACKEND=claude` with `-e OLLAMA_URL=http://host.docker.internal:11434` (no Anthropic key needed; text only).

Open http://localhost:8501. Saved records live in the `quickmove-data` volume (`/data/records.db`) and survive container restarts. Stop with `docker rm -f quickmove`. `.env` is never baked into the image.

## Local setup (without Docker)

Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill TYPESAFE_API_KEY (and ANTHROPIC_API_KEY if using Claude)
streamlit run streamlit_app.py
```

### Choosing the LLM backend

Jev always handles classification and red flags. The LLM that fills free-text fields and writes the action sentence is pluggable via `LLM_BACKEND`:

| `LLM_BACKEND` | Client | Needs | Screenshots |
|---|---|---|---|
| `ollama` (default) | `app/ollama_client.py`, local model via Ollama (`OLLAMA_MODEL`, default `qwen2.5:14b`; `OLLAMA_URL`, default `http://localhost:11434`) | Ollama running with the model pulled | No (text only) |
| `claude` | `app/claude_client.py`, Anthropic `claude-sonnet-5-5` | `ANTHROPIC_API_KEY` | Yes (Claude vision) |

```bash
streamlit run streamlit_app.py                      # Ollama
LLM_BACKEND=claude streamlit run streamlit_app.py   # Claude
```

Both clients expose the same three functions (`fill_text_fields`, `extract_with_vision`, `write_action_sentence`), so adding another backend is one new file and one line in `app/extractor.py`.

Records go to `records.db` (git-ignored). Self-checks: `python -m app.extractor`, `python -m app.store`. Live Jev check: `python -m app.jev_client`.

## Tests

25 offline tests (stdlib `unittest`, models mocked, no API keys, Ollama or network needed):

```bash
python -m unittest discover -s tests -t .
```

- **Edge cases:** empty/emoji input, Indian amount formats (`₹1,20,000`, `45k`, `1.35 lakh`), phones vs helpline numbers, date formats, red-flag thresholds and de-duplication, GST flags on quotes only, Hindi text in the DB and CSV, filters and SQL-injection-safe queries.
- **Error states:** model replies wrapped in prose or code fences, replies with no JSON, `null` list fields, corrupt images rejected before any API call, upstream outages shown as a message instead of a crash.
- **Usability:** headless UI flows for empty input, failed extraction, extract → edit → save, saving a blank record, and the empty records view.

## Schema (`VendorRecord`)

| Field | Type |
|---|---|
| message_type | quote / confirmation / delay / cancellation / availability / status / other |
| vendor_name | str? |
| vendor_category | property / logistics / utility / govt_bank / other |
| amount | {value, currency="INR", notes}? |
| dates | [{what, when}], `when` is YYYY-MM-DD when possible, else raw |
| inclusions, exclusions | [str] |
| contact | {name, phone, email}? |
| red_flags | [str], things ops should double-check |
| customer_reference | str?, move ID, customer name, city pair |
| action_needed | str, one sentence, written by Claude |
| confidence | high / medium / low |
| notes | str? |

## Model routing

TypeSafe's Jev (`/v1/systemone`) answers typed questions (choice, score, yes/no probability). It does not generate free text and takes no JSON schema, so it can't extract names or amounts on its own. The router splits the work:

| Input | Who does what |
|---|---|
| Text | **Jev**: message_type, vendor_category, confidence, red-flag probabilities (one request, 9 parallel questions). **LLM backend** (Ollama or Claude): free-text fields (vendor, amount, dates, inclusions, contact, reference), guided by regex hints. |
| Screenshot | **Claude vision** does the whole record (`LLM_BACKEND=claude`). |
| Always | The **LLM backend** writes the one-line `action_needed` (tiny prompt). |

Red flags from Jev count only at probability ≥ 0.85 (0.5 was noisy in testing); Claude can add more. `app/jev_client.py` is the only file that knows the Jev API shape.

**Cost.** Jev is ~70x cheaper per token than Claude, and its output tokens are free. Per 1M tokens: Claude Sonnet 5.5 = _(your current Anthropic price)_; Jev ≈ 1/70 of that on input, 0 on output. Because text messages are short and Jev's share (classification and flags) rides one cheap request, the Claude spend per text message is a single small fill call plus the action sentence. Screenshots pay full Claude vision cost. _(Fill in real numbers from both pricing pages before quoting.)_

## What's next

- Google Sheets write-back (replace the manual re-key)
- WhatsApp bot ingest (forward a message, get a record)
- Per-city confidence calibration

## Publish the Docker image

```bash
docker build -t <DOCKERHUB_USER>/quickmove-vendor-extractor:latest .
docker login && docker push <DOCKERHUB_USER>/quickmove-vendor-extractor:latest
```

Docker prints the image digest after the push. Paste it into the "Run with Docker" section above.

## Deploy to Streamlit Cloud

1. Push the repo to GitHub (confirm `.env` and `*.db` are git-ignored first).
2. At share.streamlit.io, create an app from the repo, main file `streamlit_app.py`.
3. In Settings → Secrets add:
   ```toml
   LLM_BACKEND = "claude"   # Cloud can't reach a local Ollama
   ANTHROPIC_API_KEY = "..."
   TYPESAFE_API_KEY = "..."
   ```
   Streamlit exposes secrets as environment variables, so the clients pick them up.
4. Note: Cloud's filesystem is ephemeral, so `records.db` resets on redeploy. Export CSV regularly, or move to a hosted DB before real use.
