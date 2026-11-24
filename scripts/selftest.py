#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Самопроверка набора: цел ли пакет и работает ли тренажёр.

Запуск из корня набора:
    python scripts/selftest.py

Что проверяет:
  1. все файлы пакета на месте;
  2. парсер видит в примерах ровно 6 вопросов и находит заголовок;
  3. в ключе примера по уровню «2 балла» на каждый вопрос и есть шкала;
  4. тренажёр поднимается, отдаёт страницу с номером сессии, принимает черновик и итог,
     пишет block_N_answers.txt/.json во временную копию (пример не портится);
  5. start.cmd в CRLF (иначе cmd.exe его не выполнит).

Только стандартная библиотека. Ничего в сети не ищет, слушает 127.0.0.1 на свободном порту.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "trainer"))
from trainer import parse_block  # noqa: E402
import trainer  # noqa: E402

OK, FAIL = [], []


def check(cond: bool, msg: str) -> None:
    (OK if cond else FAIL).append(msg)
    print(("  ok   " if cond else "  FAIL ") + msg)


def free_port(start: int = 8790) -> int:
    for port in range(start, start + 30):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("нет свободного порта")


def http_get(url: str, timeout: float = 2.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8")


def http_post(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    print("1. Файлы пакета")
    required = [
        "AGENT_BRIEF.md", "INTAKE.md", "README.md", "TRANSFER.md",
        "trainer/trainer.py", "trainer/web/app.html", "trainer/web/lesson.html",
        "trainer/web/game.html", "start.cmd",
        "templates/state.json", "templates/block.template.txt", "templates/key.template.txt",
        "templates/topic_plan.template.md", "templates/cycle_rules.txt",
        "templates/coverage.template.json",
        "scripts/coverage.py",
        "scripts/programcheck.py",
        "templates/razbor.template.txt",
        "examples/qa_block_1.txt", "examples/qa_block_1_key.txt",
        "study_example/state.json", "study_example/blocks/block_1.txt",
        "study_example/keys/block_1_key.txt",
        "skills/01-direction-diagnostic/SKILL.md", "skills/02-learning-cycle/SKILL.md",
        "skills/03-lessons-and-checks/SKILL.md", "skills/04-kit-acceptance/SKILL.md",
        "skills/05-zero-start/SKILL.md",
    ]
    for rel in required:
        check((KIT / rel).is_file(), rel)

    print("2. Парсер и примеры блоков")
    for rel in ("study_example/blocks/block_1.txt", "examples/qa_block_1.txt"):
        text = (KIT / rel).read_text(encoding="utf-8")
        info = parse_block(text)
        check(info["count"] == 6, f"{rel}: вопросов {info['count']} (ожидалось 6)")
        check(bool(info["title"]), f"{rel}: заголовок «{info['title'][:48]}…»")
        check(bool(info["subtitle"]), f"{rel}: подзаголовок есть")
        # шаблон требует, чтобы подзаголовок был строкой состава: «Сессия N: ...».
        # Без этого парсер молча съедает первый абзац как подзаголовок и блок проходит.
        check(re.match(r"^Сессия\s+\d+", info["subtitle"]) is not None,
              f"{rel}: подзаголовок — строка «Сессия N: …» -> «{info['subtitle'][:40]}…»")
        declared = re.search(r"Итого\s+(\d+)\s+вопрос", text)
        check(declared is not None and int(declared.group(1)) == info["count"],
              f"{rel}: «Итого N вопросов» сходится с парсером "
              f"({declared.group(1) if declared else '—'} против {info['count']})")

    print("3. Ключ примера")
    key = (KIT / "study_example/keys/block_1_key.txt").read_text(encoding="utf-8")
    levels = len(re.findall(r"^\s*\d+\.\s*\(2 балла\)", key, flags=re.M))
    check(levels == 6, f"уровней «2 балла» в ключе {levels} (ожидалось 6)")
    check("Шкала" in key and "сумма из 12" in key, "шкала и сумма из 12 описаны")
    for mark in ("1.5 —", "1 —", "0 —"):
        check(key.count(mark) >= 3, f"уровень «{mark}» встречается {key.count(mark)} раз")

    print("4. Тренажёр: живой прогон на временной копии")
    with tempfile.TemporaryDirectory(prefix="kit_selftest_") as tmp:
        study = Path(tmp) / "study"
        shutil.copytree(KIT / "study_example", study)
        (study / "answers").mkdir(exist_ok=True)
        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(KIT / "trainer/trainer.py"),
             "--study", str(study), "--port", str(port), "--no-browser"],
            cwd=str(KIT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{port}"
        page = ""
        for _ in range(40):
            try:
                page = http_get(base + "/")
                break
            except (urllib.error.URLError, ConnectionError):
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
        check(bool(page), "страница отдаётся")
        # номер сессии живёт в DATA (страница подставляет его скриптом), а не в разметке
        check('"session": 1' in page, "в DATA номер сессии 1")
        check("БЛОК 1" in page, "на странице заголовок блока 1")
        check(page.count("__DATA__") == 0, "подстановка DATA выполнена")

        try:
            d = http_post(base + "/draft", {"session": 1, "answers": {"1": "тест"}})
            check(d.get("ok") is True, "черновик принят")
            check((study / "answers" / "block_1_draft.json").is_file(), "черновик записан на диск")

            # страница всегда отдаёт все ключи, неотвеченные приходят пустой строкой
            save = http_post(base + "/save", {"session": 1,
                                              "answers": {"1": "тест", "2": "тест два",
                                                          "3": "cde, fgh, hgfedcba, aceg",
                                                          "4": "", "5": "", "6": ""}})
            check(save.get("ok") is True and save.get("answered") == 3, "итог принят, отвечено 3")
            txt = study / "answers" / "block_1_answers.txt"
            js = study / "answers" / "block_1_answers.json"
            check(txt.is_file() and js.is_file(), "block_1_answers.txt и .json записаны")
            body = txt.read_text(encoding="utf-8") if txt.is_file() else ""
            check("1 - тест" in body, "текстовый файл содержит ответ «1 - тест»")
            check("Без ответа: 4, 5, 6" in body, "пустые вопросы перечислены")
            data = json.loads(js.read_text(encoding="utf-8")) if js.is_file() else {}
            check(data.get("answers", {}).get("3", "").startswith("cde"), "json сохранил ответ дословно")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        time.sleep(0.3)
        with socket.socket() as s:
            s.settimeout(0.4)
            closed = s.connect_ex(("127.0.0.1", port)) != 0
        check(closed, "порт освобождён после остановки")

        print("4б. Урок, игра и нулевой старт")
        trainer.Cfg.study = study
        check(trainer.pending_page() == "", "без флага блок открывается первым")
        (study / "lesson_pending").write_text("", encoding="utf-8")
        check(trainer.pending_page() == "lesson.html", "флаг lesson_pending открывает урок")
        (study / "lesson_pending").unlink()
        (study / "game_pending").write_text("", encoding="utf-8")
        check(trainer.pending_page() == "game.html", "флаг game_pending открывает игру")
        (study / "game_pending").unlink()

        port = free_port()
        proc = subprocess.Popen(
            [sys.executable, str(KIT / "trainer/trainer.py"),
             "--study", str(study), "--port", str(port), "--no-browser"],
            cwd=str(KIT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                http_get(base + "/")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.25)
        try:
            lesson = http_get(base + "/lesson.html")
            check("три кирпича" in lesson and "__SESSION__" not in lesson,
                  "урок отдаётся, номер сессии подставлен")
            game = http_get(base + "/game.html")
            check("предскажи" in game, "игра отдаётся")
            (study / "lesson_pending").write_text("", encoding="utf-8")
            pr = http_post(base + "/progress", {"session": 1, "page": "lesson", "screen": 5,
                                                "total": 5, "finished": True})
            check(pr.get("ok") is True and pr.get("finished") is True, "прогресс урока принят")
            log = study / "answers" / "lesson_1.jsonl"
            check(log.is_file() and '"screen": 5' in log.read_text(encoding="utf-8"),
                  "лог lesson_1.jsonl записан")
            check(not (study / "lesson_pending").exists(), "флаг снят на finished=true")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    print("5. start.cmd")
    cmd = (KIT / "start.cmd").read_bytes()
    check(cmd.startswith(b"@echo off"), "начинается с @echo off")
    crlf, lf = bytes((13, 10)), bytes((10,))
    check(crlf in cmd and lf not in cmd.replace(crlf, b""), "переводы строк CRLF")
    # Табуляция в пути — не пробел: cmd её пропускает, python получает «trainer» вместо
    # «trainer\trainer.py», окно живёт до pause, и выглядит это как «ничего не открылось».
    check(b"\t" not in cmd, "в start.cmd нет символов табуляции")
    text_cmd = cmd.decode("utf-8", "replace")
    call = [ln for ln in text_cmd.splitlines() if ln.strip().lower().startswith("python ")]
    check(len(call) == 1, f"одна строка запуска python (нашлось {len(call)})")
    if len(call) == 1:
        m = re.search(r'"%~dp0([^"]+\.py)"', call[0])
        check(m is not None, "путь к скрипту в кавычках через %~dp0 (пробелы в пути)")
        if m:
            target = KIT / m.group(1).replace("\\", "/")
            check(target.is_file(), f"скрипт по этому пути существует: {m.group(1)}")
        check("--study" in call[0], "передан --study")

    print()
    print(f"Итог: ok {len(OK)}, провалов {len(FAIL)}")
    if FAIL:
        print("Пакет НЕ принят:")
        for m in FAIL:
            print("  - " + m)
        return 1
    print("Пакет принят: можно разворачивать у ученика.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
