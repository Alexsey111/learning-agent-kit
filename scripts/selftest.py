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
import selfcheck  # noqa: E402

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
        "templates/razbor_deeper.template.txt",
        "scripts/numberscheck.py",
        "scripts/razborcheck.py",
        "examples/qa_block_1.txt", "examples/qa_block_1_key.txt",
        "study_example/state.json", "study_example/blocks/block_1.txt",
        "study_example/keys/block_1_key.txt",
        "trainer/selfcheck.py",
        "demo/state.json", "demo/current.txt", "demo/coverage.json",
        "demo/keys/block_1_key.txt", "demo/keys/block_1_check.json",
        "demo/web/lesson.html", "demo/README.txt",
        "demo/gaps/block_1_razbor_example.txt",
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

    print("3б. Демо: блок, ключ и машинный образец")
    demo_block = parse_block((KIT / "demo/current.txt").read_text(encoding="utf-8"))
    check(demo_block["count"] == 3, f"демо: вопросов {demo_block['count']} (после урока — 3)")
    check(demo_block["subtitle"].startswith("Сессия 1"), "демо: подзаголовок «Сессия 1…»")
    demo_key = (KIT / "demo/keys/block_1_key.txt").read_text(encoding="utf-8")
    check(demo_key.count("(2 балла)") == 3, "демо: в ключе уровень «2 балла» на каждый вопрос")
    check("Итог: 6" in demo_key, "демо: шкала сходится (3 вопроса × 2 = 6)")
    demo_dir = KIT / "demo"
    check(selfcheck.has_check(demo_dir), "демо: машинный образец keys/block_1_check.json найден")
    sc = selfcheck.score(demo_dir, 1, {
        "1": "скидка 200 ₽, цена 800 ₽",
        "2": "960 ₽, до 1000 не хватает 40 ₽",
        "3": "25%, потому что 20% от 800 — это 160 ₽",
    })
    check(bool(sc) and sc["score"] == 6 and sc["max"] == 6,
          f"демо: полный ответ -> {sc['score'] if sc else '—'} из {sc['max'] if sc else '—'}")
    part = selfcheck.score(demo_dir, 1, {"1": "800", "2": "", "3": "не знаю"})
    check(bool(part) and part["score"] == 1,
          f"демо: частичный ответ (только цена) -> {part['score'] if part else '—'} из 6")
    zero = selfcheck.score(demo_dir, 1, {"1": "980", "2": "1000", "3": "20%"})
    check(bool(zero) and zero["score"] == 0, "демо: типичные ошибки -> 0 баллов")
    # сравнение по значению, а не по подстроке: 250 не должно закрывать шаг «25»
    check(25.0 in selfcheck.numbers("25%") and 25.0 not in selfcheck.numbers("250"),
          "демо: числа сравниваются по значению (25 ≠ 250)")
    check(selfcheck.score(KIT / "study_example", 1, {"1": "тест"}) is None,
          "обычный инстанс без образца -> проверки внутри тренажёра нет")

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

    print("4в. Демо-инстанс: урок -> блок -> проверка в браузере")
    with tempfile.TemporaryDirectory(prefix="kit_demo_") as tmp:
        demo_copy = Path(tmp) / "demo"
        shutil.copytree(KIT / "demo", demo_copy)
        (demo_copy / "answers").mkdir(exist_ok=True)
        port = free_port(8820)
        proc = subprocess.Popen(
            [sys.executable, str(KIT / "trainer/trainer.py"),
             "--study", str(demo_copy), "--port", str(port), "--no-browser"],
            cwd=str(KIT), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(40):
                try:
                    with urllib.request.urlopen(base + "/", timeout=3) as r:
                        first = r.read().decode("utf-8")
                        final_url = r.geturl()
                    break
                except (urllib.error.URLError, ConnectionError):
                    if proc.poll() is not None:
                        first, final_url = "", ""
                        break
                    time.sleep(0.25)
            check("Демо-урок" in first, "демо: корень ведёт на урок (носитель первым)")
            check(final_url.endswith("/lesson.html"), f"демо: редирект на урок ({final_url.rsplit('/', 1)[-1]})")
            check("TOTAL = 4" in first, "демо: урок на 4 экрана")

            save = http_post(base + "/save", {"session": 1, "answers": {
                "1": "800 ₽, скидка 200 ₽",
                "2": "960 ₽, до 1000 не хватает 40 ₽",
                "3": "25%, потому что 20% от 800 — это 160 ₽",
            }})
            sc = save.get("selfcheck") or {}
            check(save.get("ok") is True and sc.get("score") == 6,
                  f"демо: ответы сохранены и проверены -> {sc.get('score')} из {sc.get('max')}")
            check(bool(sc.get("razbor_path")) and Path(sc["razbor_path"]).is_file(),
                  "демо: разбор записан на диск")
            razbor = Path(sc["razbor_path"]).read_text(encoding="utf-8") if sc.get("razbor_path") else ""
            check("зачтено" in razbor and "Вопрос 3" in razbor, "демо: в разборе есть разбор по вопросам")
            check((demo_copy / "answers" / "block_1_answers.txt").is_file(),
                  "демо: файл ответов рядом (его же читает агент)")

            pr = http_post(base + "/progress", {"session": 1, "page": "lesson", "screen": 4,
                                                "total": 4, "finished": True})
            check(pr.get("ok") is True and not (demo_copy / "lesson_pending").exists(),
                  "демо: флаг урока снят после последнего экрана")
            block = http_get(base + "/")
            check("БЛОК 1" in block and "Демо-урок" not in block,
                  "демо: после урока блок открывается первым")
            check('"demo": true' in block and "Это демо" in block,
                  "демо: страница блока помечена как демо")
            check("checkBox" in block and "renderCheck" in block,
                  "демо: страница умеет показать проверку после «Готово»")
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
    check("set STUDY=demo" in text_cmd,
          "без аргумента открывается демо (первый запуск ведёт туда, где есть урок)")
    call = [ln for ln in text_cmd.splitlines() if ln.strip().lower().startswith("python ")]
    check(len(call) == 1, f"одна строка запуска python (нашлось {len(call)})")
    if len(call) == 1:
        m = re.search(r'"%~dp0([^"]+\.py)"', call[0])
        check(m is not None, "путь к скрипту в кавычках через %~dp0 (пробелы в пути)")
        if m:
            target = KIT / m.group(1).replace("\\", "/")
            check(target.is_file(), f"скрипт по этому пути существует: {m.group(1)}")
        check("--study" in call[0], "передан --study")

    print("6. Лицензия и подпись автора")
    lic = KIT / "LICENSE"
    check(lic.is_file(), "LICENSE на месте")
    if lic.is_file():
        lt = lic.read_text(encoding="utf-8", errors="replace")
        check("MIT License" in lt, "это MIT")
        check("Alexsey111" in lt, "в копирайте есть автор (Alexsey111)")
    # Подпись в страницах — это и есть исполнение условия MIT в интерфейсе:
    # копия, которую показывают людям, тянет имя автора с собой.
    for page in ("trainer/web/app.html", "trainer/web/lesson.html", "trainer/web/game.html"):
        p = KIT / page
        text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
        check("learning-agent-kit · Алексей Перминов" in text,
              f"{page}: внизу страницы подпись автора")

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
