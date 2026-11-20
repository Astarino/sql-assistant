import json
from pathlib import Path

from build_context import load_context
from decision import parse_decision
from ollama_client import build_messages
from validate_sql import validate_sql


ROOT = Path(__file__).resolve().parent


def prepare_examples(examples: list[dict], context: dict) -> dict[str, list[dict]]:
    splits = {"train": [], "valid": []}
    seen_questions = set()
    for example in examples:
        answer = json.dumps(example["answer"], ensure_ascii=False)
        decision = parse_decision(answer)
        if decision.sql is not None:
            validate_sql(decision.sql, context["database_schema"])

        for question in example["questions"]:
            normalized = question.strip().casefold()
            if normalized in seen_questions:
                raise ValueError(f"Повторный вопрос в учебных примерах: {question}")
            seen_questions.add(normalized)
            messages = build_messages(question, context)
            messages.append({"role": "assistant", "content": answer})
            splits[example["split"]].append({"messages": messages})
    return splits


def main() -> None:
    context = load_context("public", ROOT / "domain_glossary.json")
    examples = json.loads((ROOT / "training" / "examples.json").read_text(encoding="utf-8"))
    splits = prepare_examples(examples, context)

    output = ROOT / ".training-data"
    output.mkdir(exist_ok=True)
    for name, records in splits.items():
        path = output / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"{path.name}: {len(records)} примеров")


if __name__ == "__main__":
    main()
