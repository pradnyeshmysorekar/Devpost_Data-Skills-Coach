"""Devpost Data Skills Coach — a small, session-only SQL practice MVP."""

import csv
import io
import json
import os
import re
import sqlite3
from typing import Any, Callable

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()
MODEL = "gpt-5.6-luna"

# Fixed competency map: diagnostic coverage is deterministic and never AI-invented.
COMPETENCIES = [
    ("Basic SELECT and filtering (WHERE)", "Retrieve selected columns and filter rows with WHERE."),
    ("Sorting and limiting (ORDER BY, LIMIT)", "Order query results and return only the rows needed."),
    ("Aggregate functions (COUNT, SUM, AVG, MIN, MAX)", "Summarize numeric and row-level data with aggregate functions."),
    ("GROUP BY and HAVING", "Create grouped summaries and filter groups with HAVING."),
    ("NULL handling and basic data types", "Handle missing values and recognize common SQL data types safely."),
    ("Inner and outer joins", "Combine related tables with inner and outer join behavior."),
    ("Subqueries", "Use a query inside another query to express multi-step logic."),
    ("Common Table Expressions (CTEs)", "Build readable multi-step queries with WITH clauses."),
    ("Date/time functions and filtering", "Filter and transform dates and timestamps in SQL."),
    ("String functions and pattern matching (LIKE)", "Search and transform text with string functions and patterns."),
    ("Window functions (ROW_NUMBER, RANK, etc.)", "Calculate rankings and row-aware metrics without collapsing rows."),
    ("CASE statements and conditional logic", "Express conditional classifications and calculations with CASE."),
    ("Indexing and query performance basics", "Recognize how indexes and query shape affect performance."),
    ("Transactions and ACID basics", "Understand safe commit, rollback, and atomicity behavior."),
    ("Stored procedures and views", "Distinguish reusable views and stored program concepts."),
]
DIAGNOSTIC_TIERS = [
    ("Basic", list(range(0, 5))),
    ("Intermediate", list(range(5, 10))),
    ("Advanced", list(range(10, 15))),
]


DIAGNOSTIC_SCHEMA = {
    "type": "object", "properties": {"questions": {"type": "array", "minItems": 5, "maxItems": 5, "items": {
        "type": "object", "properties": {
            "kind": {"type": "string", "enum": ["multiple_choice", "sql"]},
            "prompt": {"type": "string"},
            "schema": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "expected_answer": {"type": "string"},
        }, "required": ["kind", "prompt", "schema", "options", "expected_answer"], "additionalProperties": False,
    }}}, "required": ["questions"], "additionalProperties": False,
}

DIAGNOSTIC_EVAL_SCHEMA = {
    "type": "object", "properties": {"passed": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["passed", "reason"], "additionalProperties": False,
}

LESSON_SCHEMA = {
    "type": "object", "properties": {"lesson": {"type": "string"}},
    "required": ["lesson"], "additionalProperties": False,
}

OUTLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "modules": {
            "type": "array",
            "minItems": 5,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "learning_objective": {"type": "string"},
                    "exercise_brief": {"type": "string"},
                },
                "required": ["title", "learning_objective", "exercise_brief"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["modules"],
    "additionalProperties": False,
}

EXERCISE_SCHEMA = {
    "type": "object",
    "properties": {
        "table_name": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]*$"},
        "dataset_csv": {"type": "string"},
        "sql_question": {"type": "string"},
        "correct_sql": {"type": "string"},
        "hint": {"type": "string"},
    },
    "required": ["table_name", "dataset_csv", "sql_question", "correct_sql", "hint"],
    "additionalProperties": False,
}


def client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing. Add it to your local .env file.")
    return OpenAI(api_key=key)


def json_response(instructions: str, schema_name: str, schema: dict[str, Any]) -> dict[str, Any]:
    response = client().responses.create(
        model=MODEL,
        instructions="You create precise, practical SQL learning materials for business analysts.",
        input=instructions,
        text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
    )
    return json.loads(response.output_text)


def generate_diagnostic(unit_indexes: list[int]) -> list[dict[str, Any]]:
    framework = "\n".join(f"{i + 1}. {COMPETENCIES[i][0]}: {COMPETENCIES[i][1]}" for i in unit_indexes)
    result = json_response(
        f"Create exactly one fast diagnostic question for each of these {len(unit_indexes)} competencies, in the same order. "
        "Mix multiple choice and short SQL-writing questions. Questions must be answerable in under two minutes total. "
        "Every question MUST include a visible mini-schema or small sample-data table in the schema field, with column "
        "names and SQLite-friendly types (and related table schemas when joins are tested). The question prompt must "
        "refer only to tables and columns shown in that schema. Never omit schema context. "
        "For multiple choice, provide exactly 3 or 4 options and make expected_answer exactly copy the correct option; "
        "for SQL questions, options must be an empty array and expected_answer should state the intended SQL logic.\n" + framework,
        "sql_diagnostic",
        DIAGNOSTIC_SCHEMA,
    )
    return result["questions"]


def begin_diagnostic(tier_index: int, mode: str) -> None:
    st.session_state.diagnostic_mode = mode
    st.session_state.diagnostic_tier = tier_index
    st.session_state.diagnostic_results = ["not_assessed"] * len(COMPETENCIES)
    st.session_state.diagnostic_questions = generate_diagnostic(DIAGNOSTIC_TIERS[tier_index][1])
    st.session_state.stage = "diagnostic"


def evaluate_diagnostic(question: dict[str, Any], answer: str) -> bool:
    if question["kind"] == "multiple_choice":
        return answer.strip().lower() == question["expected_answer"].strip().lower()
    result = json_response(
        "Evaluate this short SQL diagnostic answer for conceptual correctness, not exact string matching. "
        "Accept equivalent SQL logic and reasonable syntax variants. Return passed=true only when the answer fulfills "
        "the intended result.\nSchema: " + question["schema"] + "\nQuestion: " + question["prompt"] + "\nExpected logic: " + question["expected_answer"] + "\nStudent answer: " + answer,
        "diagnostic_evaluation",
        DIAGNOSTIC_EVAL_SCHEMA,
    )
    return result["passed"]


def generate_learning_path(
    gap_indexes: list[int],
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    total = len(gap_indexes)
    for position, index in enumerate(gap_indexes, start=1):
        if progress_callback:
            progress_callback(position, total, "lesson")
        label, description = COMPETENCIES[index]
        module = {
            "title": label,
            "learning_objective": description,
            "exercise_brief": f"Practice the SQL competency: {label}.",
        }
        lesson = json_response(
            f"Write a concise 3–5 sentence SQL lesson for a learner who needs this competency: {label}. "
            f"Definition: {description} Include one worked example in a fenced SQL code block. Keep it practical.",
            "sql_lesson",
            LESSON_SCHEMA,
        )["lesson"]
        module["lesson"] = lesson
        module["exercise"] = generate_exercise("diagnostic gap", index + 1, module)
        module.update({"completed": False, "attempts": 0, "original_attempts": 0, "consecutive_misses": 0,
                       "active_exercise": "original", "remediation": None, "mastered_fast": False,
                       "difficulty_adjusted": False, "competency_index": index})
        modules.append(module)
        if progress_callback:
            progress_callback(position, total, "complete")
    return modules


def create_curriculum(level: str) -> list[dict[str, Any]]:
    outline = json_response(
        f"Create exactly five progressively challenging SQL modules for a {level} business analyst. "
        "Focus on useful business questions and SQLite-compatible SQL. Give each module a concise title, "
        "a learning objective, and an exercise brief. Do not include solutions.",
        "sql_curriculum",
        OUTLINE_SCHEMA,
    )
    modules = outline["modules"]
    for index, module in enumerate(modules, start=1):
        exercise = generate_exercise(level, index, module)
        module["exercise"] = exercise
        module["completed"] = False
        module["attempts"] = 0
        module["original_attempts"] = 0
        module["consecutive_misses"] = 0
        module["active_exercise"] = "original"
        module["remediation"] = None
        module["mastered_fast"] = False
        module["difficulty_adjusted"] = False
    return modules


def generate_exercise(level: str, index: int, module: dict[str, Any], difficulty_note: str = "") -> dict[str, Any]:
    return json_response(
        f"Skill level: {level}. Module {index}: {module['title']}. Objective: {module['learning_objective']}. "
        f"Exercise direction: {module['exercise_brief']}. {difficulty_note} Create one self-contained SQL exercise. "
        "Return a realistic small synthetic CSV with a header and 8–45 data rows. Use one table only. "
        "All CSV values must be SQLite-friendly (no embedded newlines). The question must be unambiguous. "
        "Write the exact correct SQLite SELECT query. Do not use non-SQLite features or multiple statements.",
        "sql_exercise",
        EXERCISE_SCHEMA,
    )


def generate_remediation(level: str, index: int, module: dict[str, Any]) -> dict[str, Any]:
    return generate_exercise(
        level,
        index,
        module,
        "This is scaffolded remediation after two missed attempts. Keep the SAME core SQL concept, "
        "but make it simpler: fewer rows, fewer columns, and one obvious filter/aggregation step. "
        "Do not introduce a new concept.",
    )


def increase_next_difficulty(level: str, index: int, module: dict[str, Any]) -> None:
    if module.get("difficulty_adjusted"):
        return
    module["exercise"] = generate_exercise(
        level,
        index,
        module,
        "The learner mastered the prior module on the first attempt. Make this exercise slightly more challenging "
        "while staying appropriate for the selected level: add one modest layer such as a second condition, "
        "a grouping dimension, or a meaningful ordering requirement.",
    )
    module["difficulty_adjusted"] = True


def dataframe_from_csv(csv_text: str) -> pd.DataFrame:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    rows = list(reader)
    if not reader.fieldnames or not rows:
        raise ValueError("The generated dataset was empty or missing a header.")
    if len(rows) >= 50:
        raise ValueError("The generated dataset has too many rows.")
    # CSV has no native NULL token: blank cells must become Python None so
    # SQLite can evaluate IS NULL correctly (rather than treating them as '').
    dataset = pd.DataFrame(rows)
    return dataset.replace(r"^\s*$", None, regex=True)


def sqlite_numeric_dtypes(dataset: pd.DataFrame) -> dict[str, str]:
    """Infer safe SQLite affinities for numeric CSV columns.

    CSV parsing starts with strings, so explicitly identifying integer/decimal
    columns prevents SQLite from sorting values such as 90 and 650 as text.
    Columns with any non-numeric value remain TEXT (IDs with letters, dates,
    and category labels are intentionally left untouched).
    """
    dtypes: dict[str, str] = {}
    for column in dataset.columns:
        values = dataset[column].astype("string").str.strip()
        non_blank = values[values.notna() & values.ne("")]
        if non_blank.empty:
            continue
        numeric = pd.to_numeric(non_blank, errors="coerce")
        if numeric.notna().all():
            # Preserve decimal intent from the CSV (e.g. 90.00 is a REAL even
            # when its current value happens to be mathematically integral).
            has_decimal_notation = non_blank.str.contains(r"[.]|[eE]", regex=True).any()
            is_integer = (numeric % 1 == 0).all() and not has_decimal_notation
            dtypes[column] = "INTEGER" if is_integer else "REAL"
    return dtypes


def safe_select(sql: str) -> bool:
    cleaned = re.sub(r"--[^\n]*|/\*[\s\S]*?\*/", "", sql).strip().rstrip(";").strip()
    if ";" in cleaned:
        return False
    return bool(re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE))


def run_query(dataset: pd.DataFrame, table_name: str, sql: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    if not safe_select(sql):
        raise ValueError("Please submit one read-only SELECT query (a WITH query is also allowed).")
    connection = sqlite3.connect(":memory:")
    try:
        # DictReader produces strings; dtype makes SQLite apply numeric affinity
        # before evaluating ORDER BY, comparisons, and aggregates.
        dataset.to_sql(
            table_name,
            connection,
            index=False,
            if_exists="replace",
            dtype=sqlite_numeric_dtypes(dataset),
        )
        connection.set_progress_handler(lambda: 1, 1_000_000)
        cursor = connection.execute(sql.strip().rstrip(";"))
        return [column[0] for column in cursor.description], cursor.fetchall()
    finally:
        connection.close()


def equivalent(actual: tuple[list[str], list[tuple[Any, ...]]], expected: tuple[list[str], list[tuple[Any, ...]]]) -> bool:
    """Compare returned values only; aliases and column-name casing are irrelevant."""
    return actual[1] == expected[1]


def _feedback_conclusion(text: str, fallback: bool) -> bool:
    """Read the explicit first-word conclusion used by the feedback prompt."""
    first_line = text.strip().splitlines()[0].lower() if text.strip() else ""
    if re.match(r"^(correct|yes|pass)\b", first_line):
        return True
    if re.match(r"^(incorrect|not quite|no|fail)\b", first_line):
        return False
    return fallback


def feedback(question: str, submitted_sql: str, correct_sql: str, correct: bool, error: str | None = None) -> str:
    prompt = (
        f"SQL question: {question}\nStudent SQL: {submitted_sql}\nReference SQL: {correct_sql}\n"
        f"Outcome: {'correct' if correct else 'incorrect'}"
        + (f"\nExecution error: {error}" if error else "")
        + "\nStart with exactly CORRECT or INCORRECT, matching the Outcome. Then give 2-3 friendly, specific sentences explaining what worked or what to fix, "
        "and point to the relevant SQL concept. Do not dump a full replacement query."
    )
    try:
        response = client().responses.create(model=MODEL, input=prompt)
        text = response.output_text.strip()
        if _feedback_conclusion(text, correct) != correct:
            if correct:
                text = re.sub(r"(?i)\b(in)?correct\b|not quite", "matching the expected result", text)
            else:
                text = re.sub(r"(?i)\bcorrect\b|matches? the reference", "not matching the expected result", text)
            text = ("CORRECT: " if correct else "INCORRECT: ") + text
        return text
    except Exception:
        return "CORRECT: your query produces the same result as the reference answer." if correct else "INCORRECT: compare your selected columns, filters, grouping, and ordering with the question, then try again."


def grade_sql_answer(
    dataset: pd.DataFrame,
    exercise: dict[str, Any],
    submitted_sql: str,
) -> tuple[tuple[list[str], list[tuple[Any, ...]]], bool, str]:
    """Shared SQL grading for every training exercise."""
    actual = run_query(dataset, exercise["table_name"], submitted_sql)
    expected = run_query(dataset, exercise["table_name"], exercise["correct_sql"])
    value_match = equivalent(actual, expected)
    explanation = feedback(exercise["sql_question"], submitted_sql, exercise["correct_sql"], value_match)
    verdict = _feedback_conclusion(explanation, value_match)
    return actual, verdict, explanation


def reset_course() -> None:
    for key in ("stage", "modules", "active_module", "performance_history", "diagnostic_mode", "diagnostic_tier", "diagnostic_questions",
                "diagnostic_answers", "diagnostic_results", "gap_indexes", "transition_notice", "scroll_to_top"):
        st.session_state.pop(key, None)


def scroll_to_top() -> None:
    """Use a component iframe script to reset the browser viewport after rerun."""
    components.html(
        """<script>
        const scroll = () => {
          window.scrollTo(0, 0);
          try {
            const doc = window.parent.document;
            window.parent.scrollTo(0, 0);
            doc.documentElement.scrollTop = 0;
            doc.body.scrollTop = 0;
            [
              doc.querySelector('[data-testid="stAppViewContainer"]'),
              doc.querySelector('[data-testid="stMain"]'),
              doc.querySelector('section.main'),
              doc.querySelector('.main')
            ].filter(Boolean).forEach((el) => el.scrollTo(0, 0));
          } catch (e) {}
        };
        scroll();
        setTimeout(scroll, 50);
        setTimeout(scroll, 250);
        setTimeout(scroll, 600);
        setTimeout(scroll, 1000);
        </script>""",
        height=1,
    )


st.set_page_config(page_title="Data Skills Coach", page_icon="📊", layout="wide")
st.markdown("""
<style>
.coach-hero { background: linear-gradient(120deg,#0f4c81 0%,#147d92 52%,#26a69a 100%); color:white; padding:1.4rem 1.7rem; border-radius:18px; margin-bottom:1.4rem; box-shadow:0 10px 25px rgba(15,76,129,.18); }
.coach-hero .icon { font-size:2rem; vertical-align:middle; margin-right:.55rem; }
.coach-hero h1 { display:inline; font-size:2rem; letter-spacing:-.02em; }
.coach-hero p { margin:.45rem 0 0 0; opacity:.9; }
.choice-card { border:1px solid #dbe7ef; border-radius:16px; padding:.65rem .95rem .45rem; min-height:94px; background:linear-gradient(145deg,#fff,#f2f9fb); box-shadow:0 5px 15px rgba(15,76,129,.07); margin-bottom:.35rem; }
.choice-card .choice-icon { font-size:1.65rem; }
.choice-card .choice-title { display:inline; margin-left:.4rem; color:#123b5d; font-size:1.05rem; font-weight:650; }
.choice-card p { color:#557086; margin:.45rem 0 0; font-size:.9rem; }
.choice-card button, [data-testid="stButton"] button[kind="secondary"] { color:#111827 !important; border:1px solid #111827 !important; background:white !important; }
.status-bar { display:flex; height:18px; border-radius:999px; overflow:hidden; background:#edf1f4; margin:.6rem 0 1rem; box-shadow:inset 0 1px 3px rgba(0,0,0,.08); }
.status-bar span { display:block; min-width:2px; }
.status-passed { background:#22a06b; }
.status-gap { background:#e39b32; }
.status-neutral { background:#b8c2cc; }
.status-legend { color:#5f7180; font-size:.85rem; }
.module-kicker { color:#147d92; font-weight:650; letter-spacing:.03em; }
</style>
<div class="coach-hero"><span class="icon">🎯</span><h1>Data Skills Coach</h1><p>Diagnose your gaps, build momentum, and focus your time where it grows your SQL confidence.</p></div>
""", unsafe_allow_html=True)
stage = st.session_state.setdefault("stage", "landing")

if stage == "landing":
    st.header("How would you like to proceed?")
    st.write("Choose a full-level assessment or focus on one SQL tier you already know you want to improve.")
    with st.container(border=True):
        st.markdown('<div class="choice-card"><span class="choice-icon">🧭</span><span class="choice-title">Full-Level Assessment</span><p>Start broad, then progress through each tier as your foundations strengthen.</p></div>', unsafe_allow_html=True)
        if st.button("Start Full Assessment", key="full_level_assessment", use_container_width=True):
            with st.spinner(f"Preparing your {len(COMPETENCIES)}-question diagnostic…"):
                try:
                    begin_diagnostic(0, "adaptive")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Diagnostic generation failed: {exc}")
    with st.container(border=True):
        st.markdown('<div class="choice-card"><span class="choice-icon">🎯</span><span class="choice-title">Tier-Based Assessment</span><p>Choose one skill tier when you already know where you want to focus.</p></div>', unsafe_allow_html=True)
        if st.button("Choose My Focus Tier", key="tier_based_assessment", use_container_width=True):
            st.session_state.stage = "scope_tier"
            st.rerun()
    st.stop()

if stage == "scope_tier":
    st.header("Choose a tier to assess")
    st.write("This skips cross-tier gating and checks only the tier you select.")
    if st.button("Cancel / Start Over", key="cancel_scope"):
        reset_course()
        st.rerun()
    for tier_index, (tier_name, tier_units) in enumerate(DIAGNOSTIC_TIERS):
        tier_icons = {"Basic": "🌱", "Intermediate": "🎯", "Advanced": "🚀"}
        st.markdown(f'<div class="choice-card"><span class="choice-icon">{tier_icons[tier_name]}</span><span class="choice-title">{tier_name} only</span><p>Focus your diagnostic on this skill band.</p></div>', unsafe_allow_html=True)
        if st.button(f"{tier_name} only", key=f"scope_{tier_name.lower()}", use_container_width=True):
            with st.spinner(f"Preparing the {tier_name} diagnostic…"):
                try:
                    begin_diagnostic(tier_index, "focused")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Diagnostic generation failed: {exc}")
    st.stop()

if stage == "diagnostic":
    tier_index = st.session_state.diagnostic_tier
    tier_name, tier_units = DIAGNOSTIC_TIERS[tier_index]
    st.header(f"2-minute SQL diagnostic — {tier_name} tier")
    if st.session_state.pop("scroll_to_top", False):
        scroll_to_top()
    if notice := st.session_state.pop("transition_notice", None):
        st.toast(notice, icon="✅")
        st.success(notice)
    if st.button("Cancel / Start Over", key="cancel_diagnostic"):
        reset_course()
        st.rerun()
    st.write("Answer quickly — this is a skills check, not a graded course exam.")
    for question_index, question in enumerate(st.session_state.diagnostic_questions):
        st.markdown(f"**{question_index + 1}. {question['prompt']}**")
        st.code(question["schema"], language="sql")
        if question["kind"] == "multiple_choice":
            st.radio("Choose one", question["options"], key=f"diag_answer_{tier_index}_{question_index}", label_visibility="collapsed")
        else:
            st.text_input("Your SQL answer", key=f"diag_answer_{tier_index}_{question_index}")
    if st.button("Submit diagnostic", type="primary"):
        with st.spinner("Evaluating your answers…"):
            answers = [st.session_state.get(f"diag_answer_{tier_index}_{i}", "") for i in range(len(tier_units))]
            tier_results = []
            for question, answer in zip(st.session_state.diagnostic_questions, answers):
                try:
                    tier_results.append(bool(answer.strip()) and evaluate_diagnostic(question, answer))
                except Exception:
                    tier_results.append(False)
            st.session_state.diagnostic_answers = answers
            for unit_index, passed in zip(tier_units, tier_results):
                st.session_state.diagnostic_results[unit_index] = "passed" if passed else "gap"
            if all(tier_results) and st.session_state.diagnostic_mode == "adaptive" and tier_index < len(DIAGNOSTIC_TIERS) - 1:
                next_tier = tier_index + 1
                try:
                    next_questions = generate_diagnostic(DIAGNOSTIC_TIERS[next_tier][1])
                except Exception as exc:
                    st.error(f"Could not prepare the {DIAGNOSTIC_TIERS[next_tier][0]} tier: {exc}")
                    st.stop()
                # Commit the next tier only after its five questions have been
                # generated, then rerun into the diagnostic screen in-place.
                st.session_state.diagnostic_tier = next_tier
                st.session_state.diagnostic_questions = next_questions
                st.session_state.stage = "diagnostic"
                st.session_state.transition_notice = (
                    f"{tier_name} tier complete — moving to the {DIAGNOSTIC_TIERS[next_tier][0]} tier."
                )
                st.session_state.scroll_to_top = True
                st.rerun()
            st.session_state.gap_indexes = [i for i, status in enumerate(st.session_state.diagnostic_results) if status == "gap"]
            st.session_state.stage = "results"
            st.session_state.transition_notice = "Diagnostic complete — here is your results summary."
            st.session_state.scroll_to_top = True
            st.rerun()
    st.stop()

if stage == "results":
    results = st.session_state.diagnostic_results
    gaps = st.session_state.gap_indexes
    st.header("Your diagnostic results")
    if st.session_state.pop("scroll_to_top", False):
        scroll_to_top()
    if notice := st.session_state.pop("transition_notice", None):
        st.toast(notice, icon="✅")
        st.success(notice)
    st.subheader(f"You passed {sum(status == 'passed' for status in results)} of {len(COMPETENCIES)} units.")
    st.write("We stopped testing once we found where to focus your time — no point testing advanced skills before the basics are solid.")
    passed_count = sum(status == "passed" for status in results)
    gap_count = sum(status == "gap" for status in results)
    neutral_count = sum(status == "not_assessed" for status in results)
    st.markdown(
        f'<div class="status-bar"><span class="status-passed" style="width:{passed_count / len(COMPETENCIES) * 100}%"></span>'
        f'<span class="status-gap" style="width:{gap_count / len(COMPETENCIES) * 100}%"></span>'
        f'<span class="status-neutral" style="width:{neutral_count / len(COMPETENCIES) * 100}%"></span></div>'
        f'<div class="status-legend">🟢 Passed: {passed_count} &nbsp; 🟠 Gaps: {gap_count} &nbsp; ⚪ Not assessed: {neutral_count}</div>',
        unsafe_allow_html=True,
    )
    gap_count = len(gaps)
    personalized_minutes = gap_count * 45
    personalized_hours = personalized_minutes / 60
    personalized_cost = gap_count * 10
    st.caption(f"Full course baseline: {len(COMPETENCIES) * 45 / 60:g} hours, ${len(COMPETENCIES) * 10}.")
    st.info(f"Your personalized path: {gap_count} modules, ~{personalized_hours:g} hours, ${personalized_cost}")
    st.caption("Estimated study time, not video length.")
    for index, ((label, description), status) in enumerate(zip(COMPETENCIES, results)):
        if status == "passed":
            st.success(f"✓ {index + 1}. {label}")
        elif status == "gap":
            st.warning(f"Gap — {index + 1}. {label}")
        else:
            st.markdown(
                f"<span style='color:#6b7280'>Not yet assessed — {index + 1}. {label}<br>"
                "Not tested — foundational skills need attention first.</span>",
                unsafe_allow_html=True,
            )
    st.info(f"Your personalized path will focus on {len(gaps)} gap unit(s), in competency order.")
    if st.button("Build my personalized learning path", type="primary"):
        progress = st.progress(0, text=f"Generating your personalized path… (0 of {len(gaps)} modules)")
        status = st.empty()

        def show_generation_progress(position: int, total: int, phase: str) -> None:
            fraction = (position - 1) / total if phase == "lesson" else position / total
            progress.progress(fraction, text=f"Generating your personalized path… ({position} of {total} modules)")
            status.info(f"Module {position} of {total}: generating {('lesson and exercise' if phase == 'lesson' else 'ready')}…")

        with st.spinner("Generating your personalized path…"):
            try:
                st.session_state.modules = generate_learning_path(gaps, show_generation_progress)
                st.session_state.active_module = 0
                st.session_state.performance_history = {}
                st.session_state.stage = "complete" if not gaps else "path"
                progress.progress(1.0, text=f"Personalized path ready ({len(gaps)} modules)")
                status.success("Your personalized learning path is ready.")
                st.rerun()
            except Exception as exc:
                st.error(f"Path generation failed: {exc}")
    st.stop()

if stage == "complete":
    gaps = st.session_state.get("gap_indexes", [])
    gap_count = len(gaps)
    st.header("You completed your personalized path")
    st.write(f"Full course: {len(COMPETENCIES)} units vs. your path: {gap_count} units")
    st.subheader("Before / after competency view")
    statuses = st.session_state.get("diagnostic_results", ["not_assessed"] * len(COMPETENCIES))
    cols = st.columns(len(COMPETENCIES))
    for i, col in enumerate(cols):
        with col:
            st.markdown(f"**{i + 1}**")
            # Preserve the diagnostic state: assessed gaps are red initially,
            # passed units are green, and unassessed units stay neutral gray.
            initial_marker = {"gap": "🔴", "passed": "🟢"}.get(statuses[i], "⚪")
            final_marker = "🟢" if statuses[i] in {"gap", "passed"} else "⚪"
            st.markdown(initial_marker)
            st.markdown(final_marker)
    st.caption("Top row: diagnostic starting status. Bottom row: status after completing your personalized path. Gray means not assessed.")
    if st.button("Retake diagnostic"):
        reset_course()
        st.rerun()
    st.stop()

modules = st.session_state.modules
performance_history = st.session_state.setdefault("performance_history", {})
completed_count = sum(module["completed"] for module in modules)
st.progress(completed_count / len(modules), text=f"{completed_count} of {len(modules)} gap modules completed")

with st.sidebar:
    st.header("Personalized path")
    for index, module in enumerate(modules):
        marker = "✅" if module["completed"] else "○"
        if st.button(f"{marker} {index + 1}. {module['title']}", key=f"nav_{index}", use_container_width=True):
            st.session_state.active_module = index
            st.rerun()
    if performance_history:
        with st.expander("Performance history"):
            for module_index, result in performance_history.items():
                status = "mastered fast" if result["mastered_fast"] else "needed remediation"
                st.write(f"Unit {int(module_index) + 1}: {status} ({result['attempts']} attempt(s))")
    if st.button("Start over", use_container_width=True):
        reset_course()
        st.rerun()

index = st.session_state.active_module
module = modules[index]
exercise_kind = module.get("active_exercise", "original")
exercise = module.get("remediation") if exercise_kind == "remediation" else module["exercise"]
if exercise is None:
    exercise = module["exercise"]
if module.get("remediation_completed"):
    st.info("Scaffold complete — your original exercise is ready to retry.")
    module.pop("remediation_completed", None)

module_icons = ["🌱", "🧭", "🎯", "🚀", "🏆"]
st.markdown(f'<div class="module-kicker">{module_icons[index % len(module_icons)]} SKILL-BUILDING MODULE {index + 1}</div>', unsafe_allow_html=True)
st.header(f"Module {index + 1}: {module['title']}")
if exercise_kind == "remediation":
    st.caption("Scaffolded remediation: same concept, simpler steps")
st.write(f"**Concept:** {module['learning_objective']}")
st.markdown(module["lesson"])
st.subheader("Practice challenge")
st.write(exercise["sql_question"])
with st.expander("Hint"):
    st.write(exercise["hint"])

try:
    dataset = dataframe_from_csv(exercise["dataset_csv"])
except ValueError as exc:
    st.error(f"This generated exercise is invalid: {exc}. Start over to regenerate it.")
    st.stop()

st.subheader(f"Dataset: `{exercise['table_name']}`")
st.dataframe(dataset, use_container_width=True, hide_index=True)
st.download_button("Download CSV", exercise["dataset_csv"], file_name=f"{exercise['table_name']}.csv", mime="text/csv")

answer_key = f"answer_{index}_{exercise_kind}"
submitted_sql = st.text_area("Write your SQLite query", key=answer_key, height=160, placeholder=f"SELECT *\nFROM {exercise['table_name']};")

if st.button("Check my answer", type="primary", disabled=not submitted_sql.strip()):
    with st.spinner("Running your query and preparing feedback…"):
        module["attempts"] += 1
        if exercise_kind == "original":
            module["original_attempts"] += 1
        try:
            actual, correct, explanation = grade_sql_answer(dataset, exercise, submitted_sql)
            if correct:
                if exercise_kind == "remediation":
                    module["active_exercise"] = "original"
                    module["consecutive_misses"] = 0
                    module["remediation_completed"] = True
                    st.success("Great — the scaffold is complete. Now retry the original challenge.")
                else:
                    module["completed"] = True
                    module["consecutive_misses"] = 0
                    module["mastered_fast"] = module["original_attempts"] == 1
                    performance_history[str(index)] = {"first_try_correct": module["mastered_fast"], "needed_remediation": bool(module.get("remediation")), "attempts": module["attempts"], "mastered_fast": module["mastered_fast"]}
                    st.success("Correct — nice work!")
            else:
                if exercise_kind == "original":
                    module["consecutive_misses"] += 1
                st.warning("Not quite — keep iterating.")
            st.write(explanation)
            with st.expander("Your query result"):
                st.dataframe(pd.DataFrame(actual[1], columns=actual[0]), use_container_width=True, hide_index=True)
            if exercise_kind == "original" and not correct and module["consecutive_misses"] >= 2 and module.get("remediation") is None:
                with st.spinner("Creating a simpler practice step for this concept…"):
                    module["remediation"] = generate_remediation("diagnostic gap", module["competency_index"] + 1, module)
                    module["active_exercise"] = "remediation"
                    performance_history[str(index)] = {"first_try_correct": False, "needed_remediation": True, "attempts": module["attempts"], "mastered_fast": False}
                st.rerun()
        except Exception as exc:
            if exercise_kind == "original":
                module["consecutive_misses"] += 1
            st.error(f"Your query could not be evaluated: {exc}")
            st.write(feedback(exercise["sql_question"], submitted_sql, exercise["correct_sql"], False, str(exc)))
            if exercise_kind == "original" and module["consecutive_misses"] >= 2 and module.get("remediation") is None:
                with st.spinner("Creating a simpler practice step for this concept…"):
                    module["remediation"] = generate_remediation("diagnostic gap", module["competency_index"] + 1, module)
                    module["active_exercise"] = "remediation"
                    performance_history[str(index)] = {"first_try_correct": False, "needed_remediation": True, "attempts": module["attempts"], "mastered_fast": False}
                st.rerun()

if module["completed"]:
    st.caption(f"Completed after {module['attempts']} attempt(s).")
    if completed_count == len(modules):
        if st.button("See your completion summary", type="primary"):
            st.session_state.stage = "complete"
            st.rerun()
    elif st.button("Continue to next gap"):
        st.session_state.active_module = min(index + 1, len(modules) - 1)
        st.rerun()
elif module["attempts"]:
    st.caption(f"Attempts: {module['attempts']}")
