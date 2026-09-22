# 🚢 YTC Shipping Document Verification System

Automated email triage and shipping-document (SI vs. draft BL) verification pipeline, built for the **Averis Hackathon 2026**.

The system reads an inbox of shipping-operations emails, classifies each one (BL comparison request, SI request, invoice query, general, or spam), extracts the seven key fields from the Shipping Instruction (SI) and draft Bill of Lading (BL) attachments, compares them field-by-field, and flags mismatches or documents that need human review.

---

## 1. Project Structure

```
app/                    # Backend (FastAPI + pipeline)
├── api.py              # FastAPI app — serves processed results to the frontend
├── pipeline.py          # Orchestrates classify → extract → compare → escalate
├── classifier.py        # Rule-based + Gemini email classification
├── extractor.py         # Field extraction from SI/BL documents (local + Gemini fallback)
├── comparator.py        # Deterministic SI vs BL field comparison
├── escalation.py        # Detects docs that need human review
├── ratelimit_cache.py   # Rate limiter + disk cache for Gemini calls
├── loader.py             # Inbox loader (local files or HTTP server)
└── requirements.txt

frontend/               # Streamlit UI
├── app.py
├── ui.py
├── data.py
└── requirements.txt

data/                   # Sample dataset
├── inbox/               # 500+ sample emails (JSON)
├── attachments/          # SI/BL attachments (.txt, .pdf, .docx, .xlsx)
├── ground_truth.json     # Labeled answers for scoring
└── sample_submission.json

tests/
└── run_dataset_eval.py  # Scores submission.json against ground_truth.json

submission.json          # Latest generated pipeline output
docker-compose.yml
```

---

## 2. Prerequisites

- **Python 3.12+**
- **Docker & Docker Compose** (recommended — easiest path for judges)
- A **Gemini API key** (used for ambiguous-email classification and vision-based OCR fallback). A working key is already provided in `app/.env` for convenience during judging; you may swap in your own if you hit quota limits.

---

## 3. Quick Start (Docker — recommended)

This spins up the FastAPI backend only. It's the fastest way to verify the pipeline works.

```bash
docker compose up --build
```

The API will be available at **http://localhost:8000**.

Verify it's alive:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

Browse results:

```bash
curl http://localhost:8000/emails | head
curl http://localhost:8000/emails/email_004/report
```

---

## 4. Running Locally (without Docker)

### 4.1 Backend

```bash
cd app
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# .env with GEMINI_API_KEY should already exist in app/
uvicorn api:app --reload --port 8000
```

### 4.2 Frontend (Streamlit dashboard)

In a second terminal:

```bash
cd frontend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export API_BASE_URL=http://127.0.0.1:8000   # Windows: set API_BASE_URL=...
streamlit run app.py
```

Open the URL Streamlit prints (usually **http://localhost:8501**). You can browse the inbox, toggle between "Raw inbox (before)" and "Pipeline results (after)," inspect field-by-field SI/BL comparisons, and submit human review corrections.

---

## 5. Re-running the Pipeline

A precomputed `submission.json` is already included so the API/UI work out of the box. To regenerate it from scratch:

```bash
cd app
python pipeline.py ../data
```

Useful flags / subcommands:

```bash
# Process only the first N unprocessed emails
python pipeline.py ../data --limit 20

# Debug a single email end-to-end (prints field comparison table)
python pipeline.py test email_025 ../data

# Test Gemini Vision OCR on one attachment
python pipeline.py vision_test attachments/email_511_BL.pdf ../data

# Dev-only: score a random 10% holdout split against ground_truth.json
python pipeline.py holdout ../data ../data/ground_truth.json
```

The pipeline is **resumable** — it checkpoints `submission.json` every 10 emails, so re-running it skips already-processed emails.

---

## 6. Scoring the Submission

Once `submission.json` exists, evaluate it against ground truth:

```bash
cd tests
python run_dataset_eval.py
```

This prints accuracy and writes a detailed breakdown of any incorrect predictions to `evaluation_failures.txt`.

---

## 7. How It Works

1. **Classification** (`classifier.py`) — Deterministic keyword/regex rules handle the majority of emails; anything ambiguous is batched off to Gemini (`gemini-3.5-flash-lite`) with few-shot prompting. Results are cached on disk (`.llm_cache.json`) to avoid repeat API calls.
2. **Extraction** (`extractor.py`) — Parses labeled fields (shipper, consignee, notify party, ports, container count, gross weight) from `.txt`/`.pdf`/`.docx`/`.xlsx` attachments using table/line-based heuristics, falling back to Gemini (and Gemini Vision for unreadable/scanned PDFs) when local extraction is incomplete.
3. **Comparison** (`comparator.py`) — Deterministically compares SI vs. BL values per field, with normalization for company names (address vs. name-only), ports (LOCODE + multi-port strings), and numeric fields.
4. **Escalation** (`escalation.py`) — Flags emails needing human review (missing attachments, unreadable documents, wrong document type, missing values) instead of forcing a possibly-wrong automated verdict.
5. **Serving** (`api.py` + `ui.py`) — FastAPI exposes results and a review/correction workflow; Streamlit renders the inbox, comparison table, and reviewer tools.

---

## 8. Notes for Judges

- `submission.json`, `classification_debug.json`, and `.llm_cache.json` are already populated from a full run over the 500-email sample dataset — you don't need to re-run anything to explore results.
- `evaluation_failures.txt` currently shows **no failures** against `ground_truth.json` for the processed set.
- If the Gemini key in `app/.env` hits a rate/quota limit, the pipeline gracefully falls back to purely rule-based classification and local extraction — results may become slightly less complete but the app will not crash.