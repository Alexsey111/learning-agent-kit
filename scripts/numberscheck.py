#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Гейт чисел: у каждого блока есть независимый источник, и он воспроизводит числа ключа.

Зачем. Ключ писал тот же агент, что и урок, — значит «посчитал в уме» и «посчитал верно» это
одно и то же лицо. На блоке 1 по тензорам так и вышло: в правом нижнем углу A @ B стояло 16
вместо 11, и поймал это не гейт, а отдельный оракул, написанный заново по определениям.
Теперь оракул обязателен и проверяется файлами.

Что требуется от блока:

  keys/block_N_oracle.md   — паспорт проверки:
      oracle: <путь к скрипту относительно инстанса>
      вопросы: 1, 2, 3
      ожидаю: <число или форма>   (по строке на значение, выписано из ключа)

Что проверяется:

  1. паспорт есть, в нём объявлен скрипт, и скрипт существует;
  2. `вопросы:` покрывают все вопросы ключа — иначе часть чисел не проверена;
  3. скрипт запускается и не падает (код 0) в пределах таймаута;
  4. каждое `ожидаю:` встречается в выводе скрипта — числа ключа воспроизводятся;
  5. каждое `ожидаю:` встречается в тексте ключа — оракул проверяет то же, о чём блок спрашивает,
     а не удобные ему числа.

Самопроверка: на копиях сажаются четыре дефекта — нет паспорта, оракул считает другое,
ожидание не из ключа, оракул падает. Гейт обязан покраснеть на каждом.

  python scripts/numberscheck.py --study study_tensors
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
TIMEOUT = 120
OK: list[str] = []
FAIL: list[str] = []

KEY_Q_RE = re.compile(r"^(\d+)\s*\.\s*\(\s*2(?:\s*балла)?\s*\)", re.M)
KEY_Q_ALT_RE = re.compile(r"^===\s*(\d+)\.")
EXPECT_RE = re.compile(r"^\s*ожидаю\s*:\s*(.+)$", re.M | re.I)
ORACLE_RE = re.compile(r"^\s*oracle\s*:\s*(.+)$", re.M | re.I)
QUESTIONS_RE = re.compile(r"^\s*вопросы\s*:\s*(.+)$", re.M | re.I)


def check(cond: bool, msg: str) -> None:
    if cond:
        OK.append(msg)
        print(f"  ok   {msg}")
    else:
        FAIL.append(msg)
        print(f"  FAIL {msg}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def norm(text: str) -> str:
    """Сравнение чисел без зависимости от пробелов: «(2, 3)» = «(2,3)», «25 088» = «25088»."""
    return re.sub(r"\s+", "", text).replace("−", "-")


def key_questions(text: str) -> list[int]:
    found = {int(m.group(1)) for m in KEY_Q_RE.finditer(text)}
    found |= {int(m.group(1)) for m in KEY_Q_ALT_RE.finditer(text)}
    return sorted(found)


def blocks(study: Path) -> list[tuple[int, Path]]:
    out = []
    for key in sorted((study / "keys").glob("block_*_key.txt")):
        m = re.search(r"block_(\d+)_key\.txt$", key.name)
        if m:
            out.append((int(m.group(1)), key))
    return out


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
    print(f"\n=== числа: {label} ({study}) ===")
    found = blocks(study)
    if not found:
        check(False, f"{label}: нет ни одного ключа block_N_key.txt — проверять нечего")
        return
    state: dict = {}
    sp = study / "state.json"
    if sp.is_file():
        try:
            state = json.loads(read(sp))
        except Exception:  # noqa: BLE001
            state = {}
    closed = state.get("status") == "experiment_closed"

    for num, key_path in found:
        key_text = read(key_path)
        qs = key_questions(key_text)
        doc = study / "keys" / f"block_{num}_oracle.md"
        if not doc.is_file():
            if closed:
                print(f"  n/a  блок {num}: инстанс закрыт, паспорт чисел не требуется")
                continue
            check(False, f"блок {num}: нет keys/block_{num}_oracle.md — числа ключа ничем не проверены")
            continue
        text = read(doc)
        m = ORACLE_RE.search(text)
        check(bool(m), f"блок {num}: в паспорте объявлен скрипт (oracle:)")
        if not m:
            continue
        script = (study / m.group(1).strip().strip("`")).resolve()
        check(script.is_file(), f"блок {num}: скрипт {m.group(1).strip()} существует")
        if not script.is_file():
            continue

        qm = QUESTIONS_RE.search(text)
        declared = sorted({int(x) for x in re.findall(r"\d+", qm.group(1))}) if qm else []
        check(declared == qs, f"блок {num}: вопросы паспорта {declared} = вопросы ключа {qs}")

        expects = [e.strip().strip("`") for e in EXPECT_RE.findall(text)]
        check(len(expects) >= 3, f"блок {num}: ожиданий {len(expects)} (нужно 3 и больше)")

        try:
            r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                               timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            check(False, f"блок {num}: оракул не уложился в {TIMEOUT} с")
            continue
        check(r.returncode == 0,
              f"блок {num}: оракул отработал (код {r.returncode})"
              + ("" if r.returncode == 0 else f" — {r.stderr.strip().splitlines()[-1][:120] if r.stderr.strip() else 'без stderr'}"))
        if r.returncode != 0:
            continue
        out = norm(r.stdout)
        keyn = norm(key_text)
        for exp in expects:
            ne = norm(exp)
            check(ne in out, f"блок {num}: оракул воспроизводит «{exp}»")
            check(ne in keyn, f"блок {num}: «{exp}» есть в ключе (оракул проверяет то же, о чём спрашивают)")


# --- самопроверка -------------------------------------------------------------------

class SkipControl(Exception):
    pass


def mutate(tree: Path, kind: str) -> None:
    doc = tree / "keys" / "block_1_oracle.md"
    if kind == "нет паспорта чисел":
        sp = tree / "state.json"
        if sp.is_file():
            st = json.loads(read(sp))
            st["status"] = "active"   # живой трек: паспорт обязателен, в отличие от закрытой пробы
            sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        doc.unlink(missing_ok=True)
    elif kind == "оракул считает другое":
        script = tree / "oracle" / "tensors_oracle.py"
        src = read(script)
        src = src.replace('print(f"вопрос 1, sum(): {sum(flatten(A))}")',
                          'print(f"вопрос 1, sum(): {sum(flatten(A)) + 1}")')
        script.write_text(src, encoding="utf-8")
    elif kind == "ожидание не из ключа":
        doc.write_text(read(doc) + "\nожидаю: (9, 9)\n", encoding="utf-8")
    elif kind == "оракул падает":
        script = tree / "oracle" / "tensors_oracle.py"
        src = read(script)
        src = src.replace("def main() -> int:", "def main() -> int:\n    raise SystemExit(3)  # поломка", 1)
        script.write_text(src, encoding="utf-8")


CONTROLS = ["нет паспорта чисел", "оракул считает другое", "ожидание не из ключа", "оракул падает"]


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
    ap = argparse.ArgumentParser(description="Воспроизводят ли независимые оракулы числа ключей")
    ap.add_argument("--study", help="папка инстанса")
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
    print("Числа каждого блока воспроизводятся независимым оракулом.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
