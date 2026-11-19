import argparse
import json
from dataclasses import asdict
from pathlib import Path

import psycopg

from build_context import load_context
from execute_sql import execute_sql
from ollama_client import ask_model


def main() -> int:
    parser = argparse.ArgumentParser(description="Задать вопрос локальному SQL-помощнику.")
    parser.add_argument("question", help="Вопрос на обычном языке.")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--glossary", type=Path, help="Необязательный словарь выбранной базы.")
    parser.add_argument("--model", default="qwen3.5:4b", help="Имя локальной модели в Ollama.")
    parser.add_argument("--execute", action="store_true", help="Проверить и выполнить SELECT с правами чтения.")
    arguments = parser.parse_args()

    try:
        if not arguments.question.strip():
            raise ValueError("Вопрос не должен быть пустым.")
        context = load_context(arguments.schema, arguments.glossary)
        decision = ask_model(arguments.question, context, arguments.model)
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        raise SystemExit(f"Не удалось получить ответ: {error}") from None

    output = asdict(decision)
    exit_code = 0
    if arguments.execute and decision.action == "sql":
        try:
            result = execute_sql(decision.sql, context)
            output["execution"] = {"status": "success", **result}
        except (psycopg.Error, ValueError) as error:
            output["execution"] = {"status": "error", "message": str(error)}
            exit_code = 1

    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
