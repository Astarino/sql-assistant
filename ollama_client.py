import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from decision import Decision, parse_decision


def build_messages(question: str, context: dict) -> list[dict]:
    if not question.strip():
        raise ValueError("Вопрос не должен быть пустым.")

    database_context = {key: value for key, value in context.items() if key != "instructions"}
    user_message = {"context": database_context, "question": question}
    return [
        {"role": "system", "content": context["instructions"]},
        {"role": "user", "content": json.dumps(user_message, ensure_ascii=False)},
    ]


def ask_model(question: str, context: dict, model: str) -> Decision:
    payload = {
        "model": model,
        "messages": build_messages(question, context),
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 512},
    }
    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ошибка Ollama ({error.code}): {details}") from None
    except URLError:
        raise RuntimeError("Не удалось подключиться к Ollama. Запусти ollama serve.") from None
    except TimeoutError:
        raise RuntimeError("Ollama не ответила за 120 секунд. Проверь загрузку модели.") from None

    if not isinstance(result, dict):
        raise ValueError("Ollama вернула ответ неверного формата.")
    if result.get("done") is not True or result.get("done_reason") != "stop":
        raise ValueError("Генерация не завершена корректно. Ответ не принят.")
    content = result["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("Ollama вернула ответ без текста.")
    return parse_decision(content)
