import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import psycopg

from build_context import load_context
from execute_sql import execute_sql
from ollama_client import ask_model


ROOT = Path(__file__).resolve().parent
ACTIONS = ("sql", "clarify", "unsupported")
SUITES = {
    "subscriptions": ("public", "cases.json", ROOT / "domain_glossary.json"),
    "shop": ("shop_eval", "shop_cases.json", None),
}


def row_key(row: list | tuple) -> tuple:
    return tuple((isinstance(value, bool), value) for value in row)


def rows_match(case: dict, result: dict) -> bool:
    expected = case["rows"]
    column_count = len(expected[0]) if expected else case["column_count"]
    if result["truncated"] or len(result["columns"]) != column_count:
        return False

    expected_rows = [row_key(row) for row in expected]
    actual_rows = [row_key(row) for row in result["rows"]]
    if case.get("ordered"):
        return actual_rows == expected_rows
    try:
        return Counter(actual_rows) == Counter(expected_rows)
    except TypeError:
        return False


def evaluate_case(case: dict, context: dict, model: str) -> dict:
    outcome = {"id": case["id"], "expected_action": case["action"], "actual_action": None}
    started = perf_counter()
    try:
        decision = ask_model(case["question"], context, model)
    except (ValueError, KeyError, TypeError) as error:
        outcome.update(status="invalid_response", error=str(error))
    else:
        outcome.update(actual_action=decision.action, decision=asdict(decision))
        if decision.action != case["action"]:
            outcome["status"] = "wrong_action"
        elif decision.action != "sql":
            outcome["status"] = "correct"
        else:
            try:
                execution = execute_sql(decision.sql, context)
            except (psycopg.Error, ValueError) as error:
                outcome.update(status="sql_error", error=str(error))
            else:
                outcome["execution"] = execution
                outcome["status"] = "correct" if rows_match(case, execution) else "wrong_rows"
    outcome["elapsed_seconds"] = round(perf_counter() - started, 3)
    return outcome


def summarize(outcomes: list[dict]) -> dict:
    by_action = {}
    for action in ACTIONS:
        cases = [outcome for outcome in outcomes if outcome["expected_action"] == action]
        by_action[action] = {
            "total": len(cases),
            "action_correct": sum(outcome["actual_action"] == action for outcome in cases),
            "correct": sum(outcome["status"] == "correct" for outcome in cases),
        }
    return {
        "total": len(outcomes),
        "action_correct": sum(row["action_correct"] for row in by_action.values()),
        "correct": sum(row["correct"] for row in by_action.values()),
        "by_expected_action": by_action,
        "by_status": dict(Counter(outcome["status"] for outcome in outcomes)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Оценить модель на учебных задачах.")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--suite", default="subscriptions", choices=SUITES)
    parser.add_argument("--output", required=True, type=Path, help="Путь для нового JSON-отчёта.")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Файл отчёта уже существует. Укажи другой путь.")

    try:
        schema, filename, glossary = SUITES[args.suite]
        context = load_context(schema, glossary)
        cases = json.loads((ROOT / "evaluation" / filename).read_text(encoding="utf-8"))
        outcomes = []
        for case in cases:
            outcome = evaluate_case(case, context, args.model)
            outcomes.append(outcome)
            print(f"{outcome['id']}  {outcome['status']}  ({outcome['elapsed_seconds']:.1f} с)", flush=True)

        report = {"model": args.model, "suite": args.suite, "summary": summarize(outcomes), "outcomes": outcomes}
        with args.output.open("x", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2, default=str)
            file.write("\n")
    except (psycopg.Error, OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"Оценка не завершена. {error}") from None

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
