#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Гейт программы: запрос -> план -> тема -> клетки -> блок. Одна цепочка, проверяемая по файлам.

Зачем. Правила «сначала анкета, потом план, потом блок» жили текстом брифа: их можно было
соблюсти, а можно было молча перескочить — и никто бы не заметил. Проверялось только, что
в плане встречаются слова «зачем» и «клетки», а не то, что план собран из запроса человека
и что блок спрашивает про клетки своей темы.

Что проверяется:

  1. Анкета заполнена: файл есть, в нём не меньше шести пунктов и затронуты зачем, время,
     способ проверки и критерий готовности. Без этого план не из чего выводить.
  2. План тем: 3–6 тем, у каждой зачем, число сессий, клетки и чем измеряется закрытие;
     у каждой темы есть хотя бы один идентификатор клетки (t1, d3 …).
  3. `state.topics_order` совпадает с порядком тем в плане — иначе агент ведёт не тот план,
     который показал человеку.
  4. `state.current_topic` есть в этом порядке.
  5. Паспорт `coverage.json`: у каждого вопроса перечислены клетки, и все они принадлежат
     текущей теме из плана. Вопрос про чужую клетку = скачок через тему.
  6. Диагностика была: есть `gaps/diagnostic_report.txt` или режим нулевого старта
     (`state.phase == "zero"`, где диагностику заменяет урок).

Самопроверка (по умолчанию): на копиях сажаются четыре дефекта — план из двух тем, state
не по плану, клетка из чужой темы, отсутствие диагностики в обычном режиме. Гейт обязан
покраснеть на каждом и позеленеть на чистой копии.

Только стандартная библиотека. Коды: 0 — цепочка цела, 1 — нарушения, 2 — сломался сам.

  python scripts/programcheck.py --study study_tensors
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
OK: list[str] = []
FAIL: list[str] = []

ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([A-Za-z0-9_]+)\s*\|(.+)\|\s*$")
CELL_RE = re.compile(r"\b([a-z]\d{1,2})\b")
INTAKE_WORDS = (
    ("зачем", ("зачем", "цель", "хочу")),
    ("время", ("врем", "час", "сесси", "недел")),
    ("проверка", ("провер", "измер", "формат", "замер")),
    ("готовность", ("успех", "готов", "критери", "результат")),
)


class NotAProgram(Exception):
    """Инстанс — стартовая заготовка: программы ещё нет, проверять нечего."""


def check(cond: bool, msg: str) -> None:
    if cond:
        OK.append(msg)
        print(f"  ok   {msg}")
    else:
        FAIL.append(msg)
        print(f"  FAIL {msg}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def parse_plan(text: str) -> list[dict]:
    rows = []
    for line in text.split("\n"):
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        rest = m.group(3).split("|")
        if len(rest) < 4:
            continue
        why, sessions, cells, measure = (c.strip() for c in rest[:4])
        rows.append({"n": int(m.group(1)), "id": m.group(2), "why": why,
                     "sessions": sessions, "cells": cells, "measure": measure,
                     "cell_ids": sorted(set(CELL_RE.findall(cells)))})
    return rows


def pick_study(name: str | None) -> Path:
    if name:
        p = Path(name)
        return p if p.is_absolute() else KIT / name
    for candidate in ("study", "study_tensors", "study_example"):
        if (KIT / candidate).is_dir():
            return KIT / candidate
    return KIT / "study"


def run_checks(study: Path) -> None:
    label = study.name
    print(f"\n=== программа: {label} ({study}) ===")

    intake = study / "INTAKE_filled.md"
    if not intake.is_file() and not (study / "topic_plan.md").is_file():
        print(f"  n/a  {label}: нет ни анкеты, ни плана — это стартовая заготовка, а не программа; "
              f"гейт неприменим (exit 3)")
        raise NotAProgram()
    if not intake.is_file():
        check(False, f"{label}: нет INTAKE_filled.md — план не из чего выводить")
    else:
        text = read(intake).lower()
        items = len(re.findall(r"^\s*\d+[.)]\s", text, re.M))
        check(items >= 6, f"анкета: пунктов {items} (нужно 6 и больше)")
        for name, words in INTAKE_WORDS:
            check(any(w in text for w in words), f"анкета: есть про {name}")

    plan_p = study / "topic_plan.md"
    if not plan_p.is_file():
        check(False, f"{label}: нет topic_plan.md")
        return
    plan = parse_plan(read(plan_p))
    check(3 <= len(plan) <= 6, f"план: тем {len(plan)} (норма 3–6)")
    bad = [t["id"] for t in plan
           if not (t["why"] and t["sessions"] and t["measure"] and t["cell_ids"])]
    check(not bad, f"план: у каждой темы зачем/сессии/клетки/измерение (пусто у {bad})")

    state_p = study / "state.json"
    state: dict = {}
    if not state_p.is_file():
        check(False, f"{label}: нет state.json")
    else:
        try:
            state = json.loads(read(state_p))
        except Exception as exc:  # noqa: BLE001
            check(False, f"state.json не читается: {type(exc).__name__}")

    order = state.get("topics_order") or []
    plan_order = [t["id"] for t in plan]
    check(order == plan_order, f"state.topics_order = порядок плана ({order} против {plan_order})")

    current = state.get("current_topic")
    check(current in plan_order, f"state.current_topic «{current}» есть в плане")

    cov_p = study / "coverage.json"
    closed = state.get("status") == "experiment_closed"
    if closed and not cov_p.is_file():
        print(f"  n/a  инстанс закрыт (experiment_closed): паспорт покрытия не требуется")
    elif not cov_p.is_file():
        check(False, f"{label}: нет coverage.json — нечем связать блок с клетками темы")
    else:
        try:
            cov = json.loads(read(cov_p))
        except Exception as exc:  # noqa: BLE001
            check(False, f"coverage.json не читается: {type(exc).__name__}")
            cov = {}
        topic = next((t for t in plan if t["id"] == current), None)
        allowed = set(topic["cell_ids"]) if topic else set()
        questions = cov.get("questions") or {}
        check(bool(questions), "паспорт: вопросы перечислены")
        for qnum, spec in sorted(questions.items(), key=lambda kv: int(kv[0])):
            cells = [str(c) for c in (spec.get("cells") or [])]
            check(bool(cells), f"вопрос {qnum}: названы клетки, которые проверяет")
            alien = [c for c in cells if c not in allowed]
            check(not alien,
                  f"вопрос {qnum}: клетки из текущей темы {current} (чужие {alien})" if alien
                  else f"вопрос {qnum}: клетки {cells} — из темы {current}")

    diag = study / "gaps" / "diagnostic_report.txt"
    zero = state.get("phase") == "zero"
    check(diag.is_file() or zero,
          "диагностика была или режим нулевого старта"
          + (" (нулевой старт)" if zero and not diag.is_file() else ""))


# --- самопроверка гейта -------------------------------------------------------------

def mutate(tree: Path, kind: str) -> None:
    if kind == "план из двух тем":
        p = tree / "topic_plan.md"
        lines = read(p).split("\n")
        kept, dropped = [], 0
        for line in lines:
            if ROW_RE.match(line.strip()):
                dropped += 1
                if dropped > 2:
                    continue
            kept.append(line)
        p.write_text("\n".join(kept), encoding="utf-8")
    elif kind == "state не по плану":
        p = tree / "state.json"
        d = json.loads(read(p))
        d["topics_order"] = list(reversed(d.get("topics_order") or []))
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    elif kind == "клетка из чужой темы":
        p = tree / "coverage.json"
        if not p.is_file():
            raise SkipControl("у инстанса нет паспорта покрытия")
        d = json.loads(read(p))
        first = sorted((d.get("questions") or {}).keys(), key=int)[0]
        d["questions"][first].setdefault("cells", []).append("t99")
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    elif kind == "нет диагностики":
        p = tree / "state.json"
        d = json.loads(read(p))
        d["phase"] = "regular"
        p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        (tree / "gaps" / "diagnostic_report.txt").unlink(missing_ok=True)


CONTROLS = ["план из двух тем", "state не по плану", "клетка из чужой темы", "нет диагностики"]


class SkipControl(Exception):
    """Дефект неприменим к этому инстансу (например, нет паспорта покрытия)."""


def run_controls(study: Path) -> bool:
    print("\n=== Самопроверка гейта ===")
    all_ok = True
    with tempfile.TemporaryDirectory() as tmp:
        clean = Path(tmp) / "clean"
        shutil.copytree(study, clean)
        r = subprocess.run([sys.executable, __file__, "--study", str(clean), "--no-controls"],
                           capture_output=True, text=True)
        good = r.returncode == 0
        all_ok &= good
        print(f"  контроль чистый   -> exit {r.returncode} ({'ok' if good else 'ОШИБКА: гейт ругается на здоровый набор'})")
        for kind in CONTROLS:
            tree = Path(tmp) / re.sub(r"\W+", "_", kind)
            shutil.copytree(study, tree)
            try:
                mutate(tree, kind)
            except SkipControl as why:
                print(f"  дефект «{kind}» -> n/a ({why})")
                continue
            r = subprocess.run([sys.executable, __file__, "--study", str(tree), "--no-controls"],
                               capture_output=True, text=True)
            caught = r.returncode == 1
            all_ok &= caught
            print(f"  дефект «{kind}» -> exit {r.returncode} ({'пойман' if caught else 'ПРОПУЩЕН'})")
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Сходится ли цепочка запрос -> план -> тема -> клетки -> блок")
    ap.add_argument("--study", help="папка инстанса (по умолчанию study, study_tensors, study_example)")
    ap.add_argument("--no-controls", action="store_true", help="не прогонять самопроверку гейта")
    args = ap.parse_args()

    study = pick_study(args.study)
    if not study.is_dir():
        print(f"нет папки {study}")
        return 2
    try:
        run_checks(study)
    except NotAProgram:
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"гейт сломался: {type(exc).__name__}: {exc}")
        return 2

    print(f"\nИтог: ok {len(OK)}, провалов {len(FAIL)}")
    controls_ok = True
    if not args.no_controls:
        controls_ok = run_controls(study)
        if not controls_ok:
            print("Самопроверка гейта провалена: его «зелено» ничего не значит.")
    if FAIL:
        print("Нарушения:")
        for m in FAIL:
            print("  - " + m)
        return 1
    if not controls_ok:
        return 2
    print("Цепочка запрос -> план -> тема -> клетки -> блок сходится.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
