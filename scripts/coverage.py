#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Гейт покрытия: урок обязан покрывать блок, а не наоборот.

Зачем. Блок, который спрашивает больше, чем объяснил урок, — это не проверка знания,
а лотерея: человек честно прошёл экраны и всё равно упирается в «этого не было».
Такой гейт нужен на этапе проектирования урока, до выдачи блока.

Что проверяется (все проверки — по файлам, не по обещаниям):

  1. Паспорт покрытия study/coverage.json: у каждого вопроса свой список навыков (asks),
     у каждого экрана — что он учит (teaches) и чем это можно потрогать (handle).
  2. Каждый asks действительно упомянут в блоке или в эталонном ответе ключа.
     Нельзя заявить навык, которого вопрос не требует.
  3. Каждый asks покрыт каким-то экраном, и у этого экрана есть ручка: навык,
     показанный только абзацем, не считается выученным.
  4. Каждый teaches действительно встречается в тексте lesson.html: нельзя приписать
     уроку то, чего в нём нет.
  5. Числа из эталонных ответов ключа встречаются в уроке: если блок требует [5, 7, 9],
     эти числа где-то в уроке должны быть посчитаны.
  6. Число экранов в паспорте совпадает с TOTAL в самом уроке.

Самопроверка (по умолчанию): на копии набора сажаются четыре дефекта — вопрос про
невыученное, ложный teaches, экран без ручки, число, которого не было, — гейт обязан
покраснеть на каждом и позеленеть на чистой копии. Без этого «зелено» ничего не значит.

Только стандартная библиотека. Коды выхода: 0 — покрыто, 1 — есть нарушения, 2 — сломался
сам гейт (самопроверка не прошла).

  python scripts/coverage.py                        # инстанс по умолчанию
  python scripts/coverage.py --study study_tensors
  python scripts/coverage.py --no-controls
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

LEVEL_LINE = re.compile(r"^\s*(?:2|1\.5|1|0)\s*[—–-]", re.M)
QUESTION_HEAD = re.compile(r"^(\d+)\.\s*(?:\((?:2(?:\s*балла)?)\))?", re.M)
TOTAL_RE = re.compile(r"const\s+TOTAL\s*=\s*(\d+)")
NUMBER_RE = re.compile(r"\d+")
IGNORED_NUMBERS = {0, 1, 2, 3}  # длины осей, уровни, баллы — их в уроке может не быть буквой


def check(cond: bool, msg: str) -> None:
    if cond:
        OK.append(msg)
        print(f"  ok   {msg}")
    else:
        FAIL.append(msg)
        print(f"  FAIL {msg}")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).replace("\u00a0", " ").strip().lower()


def pick_study(name: str | None) -> Path:
    if name:
        p = Path(name)
        return p if p.is_absolute() else KIT / name
    for candidate in ("study", "study_tensors", "study_example"):
        if (KIT / candidate).is_dir():
            return KIT / candidate
    return KIT / "study"


def blocks_of(study: Path) -> list[Path]:
    out: list[Path] = []
    cur = study / "current.txt"
    if cur.is_file():
        out.append(cur)
    if (study / "blocks").is_dir():
        out += [p for p in sorted((study / "blocks").glob("*.txt")) if p.name != "current.txt"]
    return out


def key_of(study: Path) -> Path | None:
    keys = sorted((study / "keys").glob("*key*.txt")) if (study / "keys").is_dir() else []
    return keys[0] if keys else None


def reference_answers(key: str) -> dict[int, str]:
    """Эталонный ответ вопроса — текст до первой строки уровня (2 / 1.5 / 1 / 0)."""
    lines = key.split("\n")
    starts: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        m = QUESTION_HEAD.match(line)
        if m and "(" in line:
            starts.append((i, int(m.group(1))))
    out: dict[int, str] = {}
    for pos, (i, num) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        chunk = lines[i:end]
        cut = len(chunk)
        for j, line in enumerate(chunk[1:], start=1):
            if LEVEL_LINE.match(line):
                cut = j
                break
        out[num] = "\n".join(chunk[:cut])
    return out


def run_checks(study: Path) -> None:
    label = study.name
    lesson_p = study / "web" / "lesson.html"
    manifest_p = study / "coverage.json"
    blocks = blocks_of(study)
    key_p = key_of(study)

    if not blocks:
        check(False, f"{label}: нет блока (current.txt или blocks/*.txt)")
        return
    block_text = "\n".join(read(p) for p in blocks)
    if not lesson_p.is_file():
        check(False, f"{label}: нет урока web/lesson.html")
        return
    lesson = read(lesson_p)
    if not key_p:
        check(False, f"{label}: нет ключа в keys/")
        return
    key_text = read(key_p)
    if not manifest_p.is_file():
        check(False, f"{label}: нет паспорта покрытия coverage.json")
        return

    try:
        manifest = json.loads(read(manifest_p))
    except Exception as exc:  # noqa: BLE001
        check(False, f"coverage.json не читается: {type(exc).__name__}")
        return

    screens = manifest.get("screens") or []
    questions = manifest.get("questions") or {}
    print(f"\n=== покрытие: {label} ({study}) ===")
    check(bool(screens), f"в паспорте есть экраны ({len(screens)})")
    check(bool(questions), f"в паспорте есть вопросы ({len(questions)})")

    # 6. число экранов: паспорт против самого урока
    total = TOTAL_RE.search(lesson)
    if total:
        check(int(total.group(1)) == len(screens),
              f"экранов в уроке TOTAL={total.group(1)} и в паспорте {len(screens)}")
    else:
        check(False, "в уроке не найден TOTAL")

    # 4. teaches существует в уроке; у экрана с teaches есть ручка
    lesson_n = norm(lesson)
    for scr in screens:
        n = scr.get("n")
        teaches = scr.get("teaches") or []
        handle = (scr.get("handle") or "").strip()
        check(bool(teaches), f"экран {n}: чему-то учит ({len(teaches)})")
        for token in teaches:
            check(norm(token) in lesson_n, f"экран {n}: «{token}» действительно есть в уроке")
        if teaches:
            check(bool(handle), f"экран {n}: у навыков есть ручка, а не только текст")

    # 2 и 3. asks: есть в блоке/ключе и покрыт экраном с ручкой
    block_n, key_n = norm(block_text), norm(key_text)
    refs = reference_answers(key_text)
    covered: dict[str, list[int]] = {}
    for scr in screens:
        if (scr.get("handle") or "").strip():
            for token in scr.get("teaches") or []:
                covered.setdefault(norm(token), []).append(int(scr.get("n") or 0))

    for qnum, spec in sorted(questions.items(), key=lambda kv: int(kv[0])):
        asks = spec.get("asks") or []
        check(bool(asks), f"вопрос {qnum}: перечислено, что он спрашивает ({len(asks)})")
        for token in asks:
            t = norm(token)
            check(t in block_n or t in key_n,
                  f"вопрос {qnum}: «{token}» действительно нужен для ответа")
            where = covered.get(t, [])
            check(bool(where), f"вопрос {qnum}: «{token}» показан в уроке (экраны {where})")

    # 5. числа эталонных ответов посчитаны в уроке
    for qnum, ref in refs.items():
        nums = {int(x) for x in NUMBER_RE.findall(ref)} - IGNORED_NUMBERS
        missing = sorted(n for n in nums if not re.search(rf"(?<!\d){n}(?!\d)", lesson))
        check(not missing,
              f"вопрос {qnum}: числа эталона есть в уроке" + (f" — нет {missing}" if missing else ""))

    missing_q = {int(q) for q in questions} ^ set(refs)
    check(not missing_q, f"паспорт и ключ говорят об одних вопросах (расхождение {sorted(missing_q)})")


# --- самопроверка гейта -------------------------------------------------------------

def mutate(tree: Path, kind: str) -> None:
    man_p = tree / "coverage.json"
    man = json.loads(read(man_p))
    if kind == "вопрос про невыученное":
        man["questions"]["1"]["asks"].append("cumsum")
        blk = tree / "current.txt"
        blk.write_text(read(blk).replace("x.sum()", "x.cumsum()"), encoding="utf-8")
    elif kind == "ложный teaches":
        man["screens"][0]["teaches"].append("einsum")
    elif kind == "экран без ручки":
        for scr in man["screens"]:
            if "sum(axis=0)" in (scr.get("teaches") or []):
                scr["handle"] = ""
    elif kind == "число, которого не было":
        kp = key_of(tree)
        kp.write_text(read(kp).replace("[5, 7, 9]", "[5, 7, 999]").replace("[6, 15]", "[6, 999]"),
                      encoding="utf-8")
    man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")


CONTROLS = ["вопрос про невыученное", "ложный teaches", "экран без ручки", "число, которого не было"]


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
            mutate(tree, kind)
            r = subprocess.run([sys.executable, __file__, "--study", str(tree), "--no-controls"],
                               capture_output=True, text=True)
            caught = r.returncode == 1
            all_ok &= caught
            print(f"  дефект «{kind}» -> exit {r.returncode} ({'пойман' if caught else 'ПРОПУЩЕН'})")
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Покрывает ли урок то, что спрашивает блок")
    ap.add_argument("--study", help="папка инстанса (по умолчанию study_tensors или study_example)")
    ap.add_argument("--no-controls", action="store_true", help="не прогонять самопроверку гейта")
    args = ap.parse_args()

    study = pick_study(args.study)
    if not study.is_dir():
        print(f"нет папки {study}")
        return 2
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
    print("Урок покрывает блок.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
