#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Гейт разбора: провал объяснён, а «не понял» даёт другой заход, а не тот же текст погромче.

Зачем. Разбор — единственное место, где обучение происходит после блока, и его легко
имитировать: «вопрос 2 — 0, надо повторить теорию». Такой разбор ничего не объясняет и
ничем не проверяется. Ещё легче обмануть второй уровень: сказать «не понял» и получить
тот же текст другими словами.

Что проверяется по файлам:

  answers/block_N_answers.txt есть  ->  gaps/block_N_razbor.txt обязан быть (в живом треке);
  1. в разборе названы проваленные вопросы («Провалили: 1, 2»), и на каждый есть секция
     «Вопрос k» с тремя частями: что не так, как правильно, шаг проверки;
  2. разбор говорит числами этого блока (числа из ключа встречаются в тексте разбора);
  3. если в state.json у блока записан уровень 2 (`razbor: {"1": {"level": 2}}`) — есть
     gaps/block_N_razbor_2.txt, он объясняет, что в первом заходе не сработало, содержит
     разбор задачи по шагам («Шаг 1..3»), и это не пересказ: доля общих пятисловных
     фрагментов с первым разбором ниже 0.55;
  4. уровень 3 — gaps/block_N_razbor_3.txt с минимальными шагами и обязательным возвратом
     в урок на конкретный экран («Клетка ... не закрыта ... экран k»), тоже не копия второго.

Самопроверка: пять посаженных дефектов — нет разбора, разбор без провального вопроса,
второй разбор — копия первого, второй без шагов, третий без возврата в урок.

  python scripts/razborcheck.py --study study_tensors
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
MIN_OVERLAP = 0.55


def check(cond: bool, msg: str) -> None:
    if cond:
        OK.append(msg)
        print(f"  ok   {msg}")
    else:
        FAIL.append(msg)
        print(f"  FAIL {msg}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def words(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9()\[\],.\-]+", text.lower())


def ngrams(text: str, n: int = 5) -> set[tuple[str, ...]]:
    w = words(text)
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def overlap(a: str, b: str) -> float:
    ga, gb = ngrams(a), ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


def failed_list(razbor: str) -> list[int]:
    m = re.search(r"Провалили\s*:\s*([0-9,\sи]+)", razbor)
    return sorted({int(x) for x in re.findall(r"\d+", m.group(1))}) if m else []


def key_numbers(study: Path, block: int) -> list[str]:
    key = study / "keys" / f"block_{block}_key.txt"
    if not key.is_file():
        return []
    text = read(key)
    return sorted({n for n in re.findall(r"\d+(?:[.,]\d+)?", text) if len(n) > 1 or n in "012"})


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
    print(f"\n=== разбор: {label} ({study}) ===")
    state: dict = {}
    sp = study / "state.json"
    if sp.is_file():
        try:
            state = json.loads(read(sp))
        except Exception:  # noqa: BLE001
            state = {}
    closed = state.get("status") == "experiment_closed"
    razbor_state: dict = state.get("razbor") or {}

    answers = sorted((study / "answers").glob("block_*_answers.txt"))
    nums = sorted({int(re.search(r"block_(\d+)_answers", p.name).group(1)) for p in answers})
    nums += [int(n) for n in razbor_state if int(n) not in nums]
    if not nums:
        print("  n/a  сданных блоков нет — разбирать нечего")
        return

    for n in sorted(set(nums)):
        raz = study / "gaps" / f"block_{n}_razbor.txt"
        if not raz.is_file():
            if closed:
                print(f"  n/a  блок {n}: инстанс закрыт, разбор не требуется")
                continue
            check(False, f"блок {n}: ответы сданы, а разбора gaps/block_{n}_razbor.txt нет")
            continue
        text = read(raz)
        failed = failed_list(text)
        check(bool(failed), f"блок {n}: названы проваленные вопросы ({failed})")
        for q in failed:
            sect = re.search(rf"Вопрос\s+{q}\b", text)
            check(bool(sect), f"блок {n}, вопрос {q}: есть отдельная секция")
            if not sect:
                continue
            tail = text[sect.start():]
            nxt = re.search(r"Вопрос\s+\d+\b", tail[10:])
            body = tail[: 10 + nxt.start()] if nxt else tail
            check("Что не так" in body, f"блок {n}, вопрос {q}: названо, что не так")
            check("Как правильно" in body, f"блок {n}, вопрос {q}: есть правильный разбор")
            check(re.search(r"Шаг проверки|Проверь сам", body) is not None,
                  f"блок {n}, вопрос {q}: есть шаг проверки командой или действием")
        knums = key_numbers(study, n)
        hits = [x for x in knums if x in text]
        check(len(hits) >= 3, f"блок {n}: разбор говорит числами ключа ({len(hits)} чисел из {len(knums)})")

        level = int((razbor_state.get(str(n)) or {}).get("level") or 1)
        prev_text = text
        for lvl in (2, 3):
            if level < lvl:
                break
            deeper = study / "gaps" / f"block_{n}_razbor_{lvl}.txt"
            if not deeper.is_file():
                check(False, f"блок {n}: ученик сказал «не понял» ({lvl}-й заход), "
                             f"а gaps/block_{n}_razbor_{lvl}.txt нет")
                break
            dtext = read(deeper)
            if lvl == 2:
                check(re.search(r"не сработал", dtext, re.I) is not None,
                      f"блок {n}, уровень 2: сказано, что в первом заходе не сработало")
            steps = re.findall(r"Шаг\s+(\d+)\s*[.:]", dtext)
            check(len(steps) >= 3, f"блок {n}, уровень {lvl}: задача разобрана по шагам ({len(steps)} шт.)")
            if lvl == 3:
                check(re.search(r"экран\s*\d+", dtext, re.I) is not None,
                      f"блок {n}, уровень 3: назван экран урока для возврата")
                check(re.search(r"не закрыт", dtext, re.I) is not None,
                      f"блок {n}, уровень 3: сказано, что клетка не закрыта")
            ov = overlap(prev_text, dtext)
            check(ov < MIN_OVERLAP,
                  f"блок {n}, уровень {lvl}: это другой заход, а не пересказ "
                  f"(общих кусков {ov:.0%}, порог {MIN_OVERLAP:.0%})")
            prev_text = dtext


# --- самопроверка -------------------------------------------------------------------

class SkipControl(Exception):
    pass


def mutate(tree: Path, kind: str) -> None:
    raz = tree / "gaps" / "block_1_razbor.txt"
    if not raz.is_file() and kind != "нет разбора":
        raise SkipControl("инстанс без разбора: контроль неприменим")
    st_p = tree / "state.json"
    st = json.loads(read(st_p)) if st_p.is_file() else {}
    if kind == "нет разбора":
        st["status"] = "active"
        st_p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        raz.unlink(missing_ok=True)
    elif kind == "разбор без провального вопроса":
        text = read(raz)
        text = re.sub(r"Вопрос 2 \(0/2\)\..*?(?=Вопрос 3)", "", text, flags=re.S)
        raz.write_text(text, encoding="utf-8")
    elif kind == "второй разбор — копия первого":
        st["razbor"] = {"1": {"failed": [1, 2, 3], "level": 2}}
        st_p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        (tree / "gaps" / "block_1_razbor_2.txt").write_text(read(raz), encoding="utf-8")
    elif kind == "второй разбор без шагов":
        st["razbor"] = {"1": {"failed": [1, 2, 3], "level": 2}}
        st_p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        (tree / "gaps" / "block_1_razbor_2.txt").write_text(
            "РАЗБОР БЛОКА 1, УРОВЕНЬ 2\n\nВ первом разборе не сработал заход через форму записи.\n\n"
            "Смотрим иначе: сумма по оси исчезает, её длина пропадает из формы, остаются только\n"
            "длины других осей, а на месте свёрнутой появляется одно число на каждую комбинацию.\n"
            "Для матрицы два на три это три числа при оси ноль и два числа при оси один.\n", encoding="utf-8")
    elif kind == "третий без возврата в урок":
        st["razbor"] = {"1": {"failed": [1, 2, 3], "level": 3}}
        st_p.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        (tree / "gaps" / "block_1_razbor_2.txt").write_text(
            "РАЗБОР БЛОКА 1, УРОВЕНЬ 2\n\nВ первом разборе не сработал заход через форму записи.\n\n"
            "Шаг 1. Берём строку чисел один два три и складываем числа внутри строки → шесть.\n"
            "Шаг 2. Берём вторую строку четыре пять шесть и складываем внутри → пятнадцать.\n"
            "Шаг 3. Складываем столбцы между собой: один и четыре → пять, два и пять → семь.\n"
            "Шаг 4. Складываем всё вместе: шесть плюс пятнадцать → двадцать один.\n", encoding="utf-8")
        (tree / "gaps" / "block_1_razbor_3.txt").write_text(
            "РАЗБОР БЛОКА 1, УРОВЕНЬ 3\n\nСамый простой счёт на пальцах.\n\n"
            "Шаг 1. Положи три монеты в ряд → это одна строка.\n"
            "Шаг 2. Положи ещё три под ними → две строки по три.\n"
            "Шаг 3. Сложи монеты каждого столбца отдельно → получишь три числа.\n"
            "Шаг 4. Сложи все шесть монет → одно число.\n", encoding="utf-8")


CONTROLS = ["нет разбора", "разбор без провального вопроса", "второй разбор — копия первого",
            "второй разбор без шагов", "третий без возврата в урок"]


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
    ap = argparse.ArgumentParser(description="Разбор провалов и углубление по «не понял»")
    ap.add_argument("--study", help="папка инстанса")
    ap.add_argument("--no-controls", action="store_true", help="не прогонять самопроверку гейта")
    args = ap.parse_args()
    study = pick_study(args.study)
    if not study.is_dir():
        print(f"нет папки {study}")
        return 2
    has_answers = bool((study / "answers").is_dir() and list((study / "answers").glob("block_*_answers.txt")))
    state_p = study / "state.json"
    has_razbor = False
    if state_p.is_file():
        try:
            has_razbor = bool(json.loads(read(state_p)).get("razbor"))
        except Exception:  # noqa: BLE001
            has_razbor = False
    if not has_answers and not has_razbor:
        print(f"\n=== разбор: {study.name} ===")
        print("  n/a  блоков ещё не сдано — разбирать нечего, гейт неприменим (exit 0)")
        return 0
    try:
        run_checks(study)
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
    print("Провалы разобраны, а «не понял» даёт другой заход, а не пересказ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
