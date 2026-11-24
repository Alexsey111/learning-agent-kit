#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Второй гейт набора: проверки, выведенные из AGENT_BRIEF.md, а не из кода.

selftest.py отвечает на вопрос «цел ли пакет и работает ли тренажёр». Этот скрипт
отвечает на другой: «выполнены ли правила брифа в самих файлах цикла» — нумерация
и размер блока, ключ с четырьмя уровнями по каждому вопросу, порядок «ключ до ответов»,
поля состояния, поля плана тем, не больше двух разборов за сессию, снятые флаги входа.

Ожидания берутся из текста брифа (§2 фазы 0-5, §3 инварианты), не из поведения кода:
если бриф и код разойдутся, скрипт скажет об этом, а не подстроится.

Запуск:
    python scripts/speccheck.py                  # примеры набора и study_docker
    python scripts/speccheck.py --study <dir>     # конкретный инстанс (папка study)
    python scripts/speccheck.py --no-controls     # без самопроверки гейта

Самопроверка (по умолчанию включена): гейт обязан провалиться на посаженных дефектах
и пройти на чистой копии. Без неё «зелено» — это «ничего не найдено этим инструментом»,
а не «всё в порядке».

Коды выхода: 0 — чисто, 1 — есть нарушения, 2 — проверить не удалось (гейт упал).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent

# --- разметка блока (бриф §2 фаза 4) -------------------------------------------------
Q_RE = re.compile(r"^(\d+)\.\s+(.*)$")
H_RE = re.compile(r"^===\s*(.*?)\s*===*\s*$")

# --- два допустимых вида ключа ------------------------------------------------------
KEY_A = re.compile(r"^(\d+)\.\s*\(2 балла\)")            # «1. (2 балла) «образец»»
KEY_B = re.compile(r"^===\s*(\d+)\.\s*(.*?)\s*===*\s*$")  # «=== 1. Тема (2) ===»
L15 = re.compile(r"^\s*1\.5\s*[—–-]", re.M)
L1 = re.compile(r"^\s*1\s*[—–-]", re.M)
L0 = re.compile(r"^\s*0\s*[—–-]", re.M)
L2LINE = re.compile(r"^\s*2(?:\s*балла)?\s*[—–-]", re.M)
SUM_RE = re.compile(r"(?:сумма из|Итог[оа]?:?)\s*(\d+)")

OK, FAIL = [], []


def check(cond: bool, msg: str) -> None:
    (OK if cond else FAIL).append(msg)
    print(("  ok   " if cond else "  FAIL ") + msg)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def questions(text: str) -> list[int]:
    nums = []
    for line in text.split("\n"):
        m = Q_RE.match(line)
        if m and not line[:1].isspace():
            nums.append(int(m.group(1)))
    return nums


def block_title(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    title = lines[idx].strip() if idx < len(lines) else ""
    idx += 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    subtitle = ""
    if idx < len(lines):
        nxt = lines[idx].strip()
        if not H_RE.match(nxt) and not Q_RE.match(nxt):
            subtitle = nxt
    return title, subtitle


def key_sections(key: str) -> dict[int, str]:
    """Ключ -> {номер вопроса: текст раздела}. Понимает оба вида заголовка."""
    lines = key.split("\n")
    starts: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        m = KEY_A.match(line)
        if m:
            starts.append((i, int(m.group(1))))
            continue
        m = KEY_B.match(line)
        if m:
            starts.append((i, int(m.group(1))))
    out: dict[int, str] = {}
    for pos, (i, num) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        out[num] = "\n".join(lines[i:end])
    return out


def key_scale(key: str) -> int | None:
    m = SUM_RE.search(key)
    return int(m.group(1)) if m else None


def check_markdown(text: str, where: str) -> None:
    bad = []
    for line in text.split("\n"):
        if line[:1] in (" ", "\t"):
            continue  # код в вопросе и разборе — не разметка
        if line.startswith("#") or line.startswith("* ") or "**" in line:
            bad.append(line[:48])
    check(not bad, f"{where}: markdown-разметки нет (найдено {len(bad)}: {bad[:2]})")


def allow_count(n: int) -> bool:
    """Бриф: обычный блок 6–8 вопросов, первый после урока — 3, диагностика — 25–30."""
    return n == 3 or 6 <= n <= 8 or 25 <= n <= 30


def check_study(study: Path, label: str) -> None:
    print(f"\n=== {label} ({study}) ===")
    current = study / "current.txt"
    blocks = sorted((study / "blocks").glob("*.txt")) if (study / "blocks").is_dir() else []
    if current.is_file():
        blocks = [current] + [b for b in blocks if b.name != current.name]
    if not blocks:
        check(False, f"{label}: нет ни current.txt, ни blocks/*.txt")
        return

    total_q = 0
    for b in blocks:
        text = read(b)
        title, subtitle = block_title(text)
        nums = questions(text)
        total_q = len(nums)
        check(bool(title), f"{b.name}: заголовок «{title[:52]}»")
        check(bool(subtitle), f"{b.name}: подзаголовок (не пустая строка и не вопрос)")
        check(nums == list(range(1, total_q + 1)),
              f"{b.name}: вопросы подряд с 1 -> {nums}")
        check(allow_count(total_q),
              f"{b.name}: вопросов {total_q} (норма 6–8, первый после урока 3, диагностика 25–30)")
        check_markdown(text, b.name)

    keys = sorted((study / "keys").glob("*.txt")) if (study / "keys").is_dir() else []
    if not keys:
        check(False, f"{label}: ключа нет в {study / 'keys'}")
    qnums = set(range(1, total_q + 1))
    for k in keys:
        key = read(k)
        sections = key_sections(key)
        check(set(sections) == qnums,
              f"{k.name}: номера вопросов ключа {sorted(sections)} против блока {sorted(qnums)}")
        holes = {}
        for num, chunk in sections.items():
            levels = {
                "2": bool(L2LINE.search(chunk)) or bool(re.search(r"\(2(?:\s*балла)?\)", chunk.split("\n")[0])),
                "1.5": bool(L15.search(chunk)),
                "1": bool(L1.search(chunk)),
                "0": bool(L0.search(chunk)),
            }
            missing = [name for name, present in levels.items() if not present]
            if missing:
                holes[num] = missing
        check(not holes, f"{k.name}: у каждого вопроса четыре уровня; дырки {holes}")
        scale = key_scale(key)
        check(scale == total_q * 2,
              f"{k.name}: шкала {scale} сходится с {total_q} вопросами x 2 = {total_q * 2}")
        check_markdown(key, k.name)

        answers = [p for p in (study / "answers").glob("block_*_answers.txt")] if (study / "answers").is_dir() else []
        if answers:
            newest = max(answers, key=lambda p: p.stat().st_mtime)
            check(k.stat().st_mtime <= newest.stat().st_mtime,
                  f"{k.name}: ключ написан до ответов ({k.stat().st_mtime:.0f} <= {newest.stat().st_mtime:.0f})")
        else:
            print(f"  n/a  {k.name}: ответов нет — порядок «ключ до ответов» не проверить")

    state_p = study / "state.json"
    if not state_p.is_file():
        check(False, f"{label}: нет state.json")
    else:
        try:
            state = json.loads(read(state_p))
        except Exception as exc:  # noqa: BLE001
            check(False, f"state.json не читается: {type(exc).__name__}")
            state = {}
        if isinstance(state, dict) and state:
            for field, typ in (("session", int), ("topics_order", list), ("review_queue", list),
                               ("gaps", list), ("history", list)):
                check(isinstance(state.get(field), typ), f"state.json: поле {field} типа {typ.__name__}")
            check(isinstance(state.get("session"), int) and state.get("session", 0) >= 1,
                  f"state.json: сессия {state.get('session')}")
            offsets = (state.get("rules") or {}).get("review_offsets")
            check(offsets == [3, 10], f"state.json: очередь повторов +3 и +10 (сейчас {offsets})")

    plan = study / "topic_plan.md"
    if plan.is_file():
        text = read(plan).lower()
        fields = [f for f in ("зачем", "сесси", "клетк", "измер") if f in text]
        check(len(fields) == 4, f"topic_plan.md: у тем есть зачем/сессии/клетки/измерение (нашлось {fields})")
    else:
        print(f"  n/a  {label}: topic_plan.md ещё не собран (фаза 3 впереди)")

    gaps = study / "gaps"
    if gaps.is_dir():
        razbory = [p.name for p in gaps.glob("*") if "razbor" in p.name.lower()]
        check(len(razbory) <= 2, f"gaps/: разборов {len(razbory)} (норма не больше двух за сессию)")

    for flag in ("lesson_pending", "game_pending"):
        flag_p = study / flag
        if not flag_p.is_file():
            continue
        name = flag.split("_")[0]
        log = study / "answers" / f"{name}_{state.get('session', 0)}.jsonl"
        finished = False
        if log.is_file():
            rows = [json.loads(line) for line in read(log).split("\n") if line.strip()]
            finished = bool(rows) and bool(rows[-1].get("finished"))
        if finished:
            check(False, f"флаг {flag} висит, хотя {name}_{state.get('session', 0)} уже завершён — "
                         f"страница откроется не та")
        else:
            check(True, f"флаг {flag} на месте, {name} ещё не пройден — откроется он")


# --- самопроверка гейта -------------------------------------------------------------
def plant(tree: Path, kind: str) -> None:
    if kind == "нет уровня 1.5":
        p = tree / "study_example/keys/block_1_key.txt"
        text = read(p).split("\n")
        for i, line in enumerate(text):
            if L15.match(line):
                del text[i]
                break
        p.write_text("\n".join(text), encoding="utf-8")
    elif kind == "сбита нумерация":
        p = tree / "study_example/blocks/block_1.txt"
        p.write_text(read(p).replace("\n3. ", "\n4. ", 1), encoding="utf-8")
    elif kind == "markdown в блоке":
        p = tree / "study_example/blocks/block_1.txt"
        p.write_text(read(p).replace("\n1. ", "\n# Вопрос 1\n1. ", 1), encoding="utf-8")
    elif kind == "нет сессии в state":
        p = tree / "study_example/state.json"
        data = json.loads(read(p))
        data.pop("session", None)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    elif kind == "ключ новее ответов":
        ans = tree / "study_example/answers/block_1_answers.txt"
        ans.parent.mkdir(parents=True, exist_ok=True)
        ans.write_text("1 - ответ\n", encoding="utf-8")
        import os
        os.utime(ans, (1_600_000_000, 1_600_000_000))
    else:
        raise SystemExit(f"неизвестный дефект: {kind}")


CONTROLS = ["нет уровня 1.5", "сбита нумерация", "markdown в блоке",
            "нет сессии в state", "ключ новее ответов"]


def run_controls() -> bool:
    """Гейт обязан провалиться на каждом посаженном дефекте и пройти на чистой копии."""
    print("\n=== Самопроверка гейта (положительный и отрицательный контроль) ===")
    ok = True
    with tempfile.TemporaryDirectory(prefix="speccheck_ctrl_") as tmp:
        clean = Path(tmp) / "clean"
        shutil.copytree(KIT, clean, ignore=shutil.ignore_patterns("__pycache__", ".git"))
        rc = subprocess_run(clean)
        print(f"  контроль чистый   -> exit {rc} " + ("(ok)" if rc == 0 else "(ОШИБКА: гейт ругается на здоровый набор)"))
        ok = ok and rc == 0
    for kind in CONTROLS:
        with tempfile.TemporaryDirectory(prefix="speccheck_ctrl_") as tmp:
            tree = Path(tmp) / "kit"
            shutil.copytree(KIT, tree, ignore=shutil.ignore_patterns("__pycache__", ".git"))
            plant(tree, kind)
            rc = subprocess_run(tree)
            caught = rc == 1
            print(f"  дефект «{kind}» -> exit {rc} " + ("(пойман)" if caught else "(ПРОПУЩЕН)"))
            ok = ok and caught
    return ok


def subprocess_run(tree: Path) -> int:
    import subprocess
    p = subprocess.run([sys.executable, str(tree / "scripts" / "speccheck.py"), "--no-controls"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Проверки из AGENT_BRIEF по файлам цикла")
    ap.add_argument("--study", action="append", default=[], help="папка study (можно несколько раз)")
    ap.add_argument("--no-controls", action="store_true", help="без самопроверки гейта")
    args = ap.parse_args()

    targets = [Path(s).resolve() for s in args.study]
    if not targets:
        targets = [KIT / "study_example", KIT / "study_docker"]
    for t in targets:
        if not t.is_dir():
            print(f"нет папки: {t}")
            return 2

    try:
        for t in targets:
            check_study(t, t.name)
        examples = KIT / "examples"
        if examples.is_dir() and not args.study:
            for b in sorted(examples.glob("*_block_*.txt")):
                nums = questions(read(b))
                check(nums == list(range(1, len(nums) + 1)), f"examples/{b.name}: нумерация подряд -> {nums}")
                check(allow_count(len(nums)), f"examples/{b.name}: вопросов {len(nums)}")
                check_markdown(read(b), f"examples/{b.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"\nПроверить не удалось: {type(exc).__name__}: {exc}")
        return 2

    print(f"\nИтог: ok {len(OK)}, провалов {len(FAIL)}")
    controls_ok = True
    if not args.no_controls:
        controls_ok = run_controls()
        if not controls_ok:
            print("Самопроверка гейта провалена: его «зелено» ничего не значит.")
    if FAIL:
        print("Нарушения:")
        for m in FAIL:
            print("  - " + m)
        return 1
    if not controls_ok:
        return 2
    print("Файлы цикла соответствуют брифу.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
