import argparse
import json
from dataclasses import asdict
from pathlib import Path

import psycopg

from build_context import load_context
from ollama_client import ask_model


def main() -> None:
    parser = argparse.ArgumentParser(description="Задать вопрос локальному SQL-помощнику.")
    parser.add_argument("question", help="Вопрос на обычном языке.")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--glossary", type=Path, help="Необязательный словарь выбранной базы.")
    parser.add_argument("--model", default="qwen3.5:4b", help="Имя локальной модели в Ollama.")
    arguments = parser.parse_args()

    try:
        if not arguments.question.strip():
            raise ValueError("Вопрос не должен быть пустым.")
        context = load_context(arguments.schema, arguments.glossary)
        decision = ask_model(arguments.question, context, arguments.model)
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        raise SystemExit(f"Не удалось получить ответ: {error}") from None

    print(json.dumps(asdict(decision), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
