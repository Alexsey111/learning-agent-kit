#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Демо-проверка ответов внутри тренажёра.

Зачем это нужно. Весь цикл проверки в наборе выполняет агент: читает файл ответов,
сверяет с ключом и пишет разбор. Пока агент не подключён, человек после кнопки
«Готово» видит только «сохранено» — и не может убедиться, что проверка вообще есть.
Демо-инстанс приносит с собой keys/block_N_check.json: короткий машинный образец
ответа. По нему тренажёр сам считает балл и показывает, каких чисел не хватило.

Это не замена ключу и не замена агенту. Проверка здесь грубая: она ищет числа,
а не смысл, и не объясняет причину ошибки. В рабочем цикле ключ
(keys/block_N_key.txt) читает агент и пишет разбор словами.

Формат keys/block_N_check.json:

    {
      "mode": "demo",
      "note": "одна строка о том, что это демо",
      "questions": {
        "1": {
          "max": 2,
          "etalon": "скидка 200 ₽, цена 800 ₽",
          "steps": [
            {"any": ["800"], "why": "цена после скидки: 1000 − 200 = 800"},
            {"any": ["200"], "why": "размер скидки: 20% от 1000 = 200"}
          ]
        }
      }
    }

Шаг засчитывается, если в ответе есть любое из чисел `any` (сравнение по значению,
а не по подстроке: 25 не засчитается за 250). Балл вопроса = max × (зачтённые шаги /
все шаги), округление до половины балла — как в ключе со шкалой 0 / 1 / 1.5 / 2.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
CHECK_GLOB = "keys/block_*_check.json"


def check_path(study: Path, session: int) -> Path:
    return study / "keys" / f"block_{session}_check.json"


def has_check(study: Path) -> bool:
    """Есть ли в инстансе демо-образец (по нему страница рисует плашку «демо»)."""
    return any((study / "keys").glob("block_*_check.json")) if (study / "keys").is_dir() else False


def numbers(text: str) -> set[float]:
    """Все числа из ответа как значения: «800 ₽», «0,8», «-20» -> {800.0, 0.8, -20.0}."""
    out: set[float] = set()
    for raw in NUM_RE.findall(str(text or "").replace("\u00a0", " ").replace("\u202f", " ")):
        try:
            out.add(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return out


def load(study: Path, session: int) -> dict | None:
    path = check_path(study, session)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — битый образец не должен ломать сохранение
        print(f"предупреждение: {path.name} не читается ({type(exc).__name__}), проверка пропущена",
              flush=True)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("questions"), dict):
        print(f"предупреждение: {path.name} без поля questions, проверка пропущена", flush=True)
        return None
    return data


def score(study: Path, session: int, answers: dict[str, str]) -> dict | None:
    """Ответы -> результат демо-проверки. None, если образца нет (обычный инстанс)."""
    data = load(study, session)
    if data is None:
        return None

    rows: list[dict] = []
    got = 0.0
    total = 0.0
    for num, spec in data["questions"].items():
        if not isinstance(spec, dict):
            continue
        mx = float(spec.get("max") or 2)
        total += mx
        answer = answers.get(str(num), "")
        found = numbers(answer)
        steps: list[dict] = []
        hit = 0
        for step in spec.get("steps") or []:
            needles = step.get("any") or []
            ok = any(abs(n - v) < 1e-9 for n in numbers(" ".join(map(str, needles))) for v in found)
            hit += 1 if ok else 0
            steps.append({"why": str(step.get("why") or ""), "ok": ok})
        part = mx * (hit / len(steps)) if steps else 0.0
        part = round(part * 2) / 2  # шкала ключа: 0 / 1 / 1.5 / 2
        got += part
        rows.append({"num": str(num), "score": part, "max": mx,
                     "answer": str(answer or "").strip(), "etalon": str(spec.get("etalon") or ""),
                     "steps": steps, "empty": not str(answer or "").strip()})

    rows.sort(key=lambda r: int(r["num"]) if r["num"].isdigit() else 999)
    return {"demo": True, "note": str(data.get("note") or ""), "score": got,
            "max": total, "questions": rows}


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def render_razbor(payload: dict, session: int) -> str:
    """Текстовый разбор демо-проверки — тот же файл, что в рабочем цикле пишет агент.

    Смысл файла: человек видит на диске ровно то место, куда смотрит агент. Поэтому
    формат тот же (что получилось / по вопросам / итог), но объяснений меньше: демо
    умеет только сказать, какого числа не хватило, и показать эталон.
    """
    lines = [f"РАЗБОР БЛОКА {session} — демо-проверка тренажёра", ""]
    lines.append(f"Итог: {_num(payload['score'])} из {_num(payload['max'])} баллов. "
                 "Проверка демонстрационная: тренажёр ищет в ответе ключевые числа.")
    lines.append("")
    lines.append("=== По вопросам ===")
    lines.append("")
    for row in payload["questions"]:
        lines.append(f"Вопрос {row['num']} — {_num(row['score'])} из {_num(row['max'])}.")
        if row["empty"]:
            lines.append("Ответа нет. В рабочем цикле это не провал: агент сначала спросит, "
                         "что осталось непонятным.")
        for step in row["steps"]:
            lines.append(("  зачтено:  " if step["ok"] else "  не хватило: ") + step["why"])
        if row["etalon"]:
            lines.append(f"  эталон: {row['etalon']}")
        lines.append("")
    lines.append("=== Что дальше ===")
    lines.append("")
    lines.append("В рабочем цикле этот файл пишет агент: по каждому провалу — что не так, "
                 "как правильно и какой командой проверить. Здесь проверка грубая: она "
                 "видит число, но не видит смысл.")
    lines.append("")
    return "\n".join(lines)
