import json
from dataclasses import dataclass


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["sql", "clarify", "unsupported"]},
        "sql": {"type": ["string", "null"]},
        "message": {"type": "string", "minLength": 1},
    },
    "required": ["action", "sql", "message"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Decision:
    action: str
    sql: str | None
    message: str

    def __post_init__(self) -> None:
        if self.action not in ("sql", "clarify", "unsupported"):
            raise ValueError("Неизвестное действие помощника.")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("Помощник должен вернуть непустое сообщение.")
        if self.action == "sql":
            if not isinstance(self.sql, str) or not self.sql.strip():
                raise ValueError("Для действия sql нужен непустой SQL-запрос.")
        elif self.sql is not None:
            raise ValueError("Для clarify и unsupported поле sql должно быть null.")


def parse_decision(response: str) -> Decision:
    data = json.loads(response)
    if not isinstance(data, dict):
        raise ValueError("Ответ помощника должен быть JSON-объектом.")
    if set(data) != {"action", "sql", "message"}:
        raise ValueError("В ответе должны быть только поля action, sql и message.")
    return Decision(**data)
