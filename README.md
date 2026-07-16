# Data Skills Coach

**Diagnose your exact SQL skill gaps — then learn only what you're actually missing, not a generic course.**

Most SQL training makes you sit through content you already know just to reach the two or three concepts you actually need. Data Skills Coach flips that: it diagnoses your specific gaps first, then builds a personalized learning path around only those gaps — nothing else.

## The Problem

Generic courses sell a fixed bundle. Whether you need 2 units or 12, you pay for and sit through all of them. For learners trying to get job-ready fast — or professionals brushing up before an interview — that's wasted time and, often, wasted money.

## Who This Is For

Learners who are unsure which specific SQL skills they're missing and don't want to relearn what they already know — students preparing for data roles, professionals refreshing before a job switch, or anyone who wants a fast, honest read on where they actually stand.

## How It Works

1. **Choose your path** — a full adaptive assessment across three tiers, or jump straight into one tier you already know you want to focus on.
2. **Tiered diagnostic** — Basic (5 questions), Intermediate (5), Advanced (5), covering 15 core SQL competencies. The diagnostic stops the moment it finds your ceiling — no point testing advanced skills before the basics are confirmed solid.
3. **Gap results** — a clear breakdown of what you've passed, what's a genuine gap, and what wasn't tested yet (and why).
4. **Personalized path** — for every gap unit only, a short concept lesson with a worked example, followed by a hands-on SQL exercise against a real synthetic dataset, graded by executing your query and comparing actual results.
5. **Completion summary** — a before/after view showing exactly how much of the full 15-unit course you actually needed versus what a generic course would have made you sit through.

## Built With Codex + GPT-5.6

Codex built the full Streamlit application in a single continuous session, including the diagnostic engine, SQLite-backed grading logic, dynamic content generation, and UI. GPT-5.6 (Luna tier) powers the app at runtime: generating diagnostic questions and synthetic datasets, writing lesson content and exercises tailored to each detected gap, and producing grading feedback.

**Where Codex accelerated the work:** the entire application — routing, session-state management, SQLite integration, and prompt orchestration — was scaffolded and iterated on inside Codex from a single continuous build brief, turning a multi-day build into a single working session.

**Key decisions made along the way:**
- Restructured the diagnostic from a flat 14-question list into three gated tiers (5/5/5 across 15 competencies) after identifying that adaptive, ceiling-finding assessment is both faster for the user and a more credible testing methodology than a flat quiz.
- Identified and directed the fix for a critical grading defect: the app was judging answers by the *sound* of the SQL rather than by executing it, producing both false positives (an incomplete query marked "Correct") and false negatives (a correct query marked wrong due to column-name casing). Fixed by moving to execution-based grading — the user's query and a reference query are both run against the real in-memory dataset and their actual results compared, with GPT-5.6 used only to generate feedback *after* that deterministic check.
- Traced and fixed a data-integrity bug where blank values in generated datasets were stored as empty strings instead of true SQL `NULL`, silently breaking `IS NULL` and `COALESCE` logic, and a related bug where numeric columns were sorting lexicographically instead of numerically.
- Chose the GPT-5.6 Luna tier over the default Sol tier for a roughly 5x cost reduction with no meaningful quality loss for this task, after reviewing actual per-request API pricing.

## Setup & Run

```bash
python -m venv venv
venv\Scripts\activate        # Windows PowerShell: .\venv\Scripts\Activate.ps1
pip install streamlit openai python-dotenv
```

Create a `.env` file in the project root:
```
OPENAI_API_KEY=your_key_here
```

Run the app:
```bash
streamlit run app.py
```

## Known Limitations / Future Work

- Scoped to SQL only for this MVP; the underlying diagnostic-then-train architecture is designed to extend to Python, ETL, and other data skills.
- Generated lesson content is not human-reviewed for accuracy — acceptable for a hackathon MVP, but a review layer is the natural next step for production use.
- Session-based only; no persistent accounts or long-term progress history across sessions yet.
- Currently supports individual, self-directed learners; an organizational onboarding mode (training built against a company's real schema) and job-posting-targeted learning paths were explored during development and are natural next extensions.

## License

Built for the OpenAI Build Week Hackathon (July 2026).
