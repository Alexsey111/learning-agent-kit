#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальный тренажёр цикла обучения: вопросы в браузере, ответы в файл.

Ничего не отправляет в сеть, слушает только 127.0.0.1.
Только стандартная библиотека — зависимостей нет, ставится копированием.

Запуск:
    python trainer.py                          # папка study рядом со скриптом, порт 8765+
    python trainer.py --study study_example     # другая папка данных
    python trainer.py --port 8770 --no-browser  # фиксированный порт, без открытия окна

Что ждёт на диске (см. templates/):
    study/current.txt              текущий блок: заголовок, подзаголовок, секции ===, вопросы "N. ..."
    study/state.json               {"session": N, ...} — номер блока, он же номер файла ответов
    study/answers/                 сюда пишутся block_N_answers.txt / .json и block_N_draft.json
    web/app.html                   страница блока (в неё подставляется __DATA__)
    web/*.html                     любые другие страницы (уроки, приборы) отдаются как есть

Маршруты:
    GET  /              блок текущей сессии
    GET  /<file>.html   статическая страница из web/ (урок, прибор), __SESSION__ заменяется номером
    POST /draft         автосохранение черновика {"session": N, "answers": {"1": "..."}}
    POST /save          итоговый файл ответов
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

Q_RE = re.compile(r"^(\d+)\.\s+(.*)$")
H_RE = re.compile(r"^===\s*(.*?)\s*===*\s*$")
PAGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_BODY = 2_000_000  # больше — не ответ ученика, а мусор


def page_name(value: object) -> str:
    """Имя страницы из тела запроса -> безопасное имя файла или "".

    Слэши, точки и «..» отбрасываются целиком: имя страницы — это метка носителя
    (lesson, game, свой прибор), а не путь. Иначе вызывающий выбирает, куда писать.
    """
    text = str(value or "").strip()
    return text if PAGE_RE.match(text) else ""



class Cfg:
    study: Path = ROOT / "study"
    open_browser: bool = True

    @classmethod
    def current(cls) -> Path:
        return cls.study / "current.txt"

    @classmethod
    def state(cls) -> Path:
        return cls.study / "state.json"

    @classmethod
    def answers(cls) -> Path:
        return cls.study / "answers"


def read_session() -> int:
    try:
        return int(json.loads(Cfg.state().read_text(encoding="utf-8")).get("session", 0))
    except Exception:  # noqa: BLE001
        return 0


def parse_block(text: str) -> dict:
    """Блок -> {title, subtitle, blocks[{t,text}|{t:q,num,text}], count}.

    Правила разметки: первая непустая строка — заголовок; следующая — подзаголовок,
    если не начинается с "N. " или "=== "; "=== ТЕКСТ ===" — секция; "N. текст"
    с нулевой колонки — вопрос, продолжение вопроса — с отступом.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict] = []
    para: list[str] = []
    q: dict | None = None

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
            idx += 1
    lines = lines[idx:]

    def flush_para() -> None:
        nonlocal para
        if para:
            blocks.append({"t": "p", "text": " ".join(para).strip()})
            para = []

    def flush_q() -> None:
        nonlocal q
        if q is not None:
            # сжимаем пробелы внутри строк, но переносы кода оставляем
            q["text"] = "\n".join(re.sub(r"[ \t]+", " ", s).strip()
                                  for s in q["text"].split("\n")).strip()
            blocks.append(q)
            q = None

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_para()
            flush_q()
            continue
        m = H_RE.match(stripped)
        if m:
            flush_para()
            flush_q()
            blocks.append({"t": "h", "text": m.group(1)})
            continue
        m = Q_RE.match(line)
        if m and not line[:1].isspace():
            flush_para()
            flush_q()
            q = {"t": "q", "num": int(m.group(1)), "text": m.group(2)}
            continue
        if q is not None:
            # строка с отступом — код: перенос сохраняем, иначе Dockerfile слипается в одну строку
            q["text"] += ("\n" + line.rstrip()) if line[:1].isspace() else (" " + stripped)
            continue
        para.append(stripped)

    flush_para()
    flush_q()
    return {"title": title, "subtitle": subtitle, "blocks": blocks,
            "count": len([b for b in blocks if b["t"] == "q"])}


def render_html(payload: dict) -> str:
    tpl = (WEB / "app.html").read_text(encoding="utf-8")
    return tpl.replace("__DATA__", json.dumps(payload, ensure_ascii=False))


PAGES = ("lesson", "game")  # необязательные страницы с проверкой на месте


def pending_page() -> str:
    """Флаг входа: study/<page>_pending -> открыть эту страницу вместо блока.

    Носитель (урок, игра) ставится первым экраном, иначе его не откроют.
    Флаг снимается, когда страница прислала finished=true в /progress.
    """
    for name in PAGES:
        if (Cfg.study / f"{name}_pending").exists():
            return f"{name}.html"
    return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "LearningCycleTrainer/2.0"

    def log_message(self, fmt: str, *args) -> None:  # тише в консоли
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                payload = parse_block(Cfg.current().read_text(encoding="utf-8"))
            except FileNotFoundError:
                self._send(500, "study/current.txt не найден — блок не подготовлен".encode("utf-8"),
                           "text/plain; charset=utf-8")
                return
            payload["session"] = read_session()
            self._send(200, render_html(payload).encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
            return
        if path.endswith(".html"):
            name = path.lstrip("/")
            # страницы инстанса (study/web) важнее шаблонных: урок и игра живут рядом с данными
            for base in (Cfg.study / "web", WEB):
                page = base / name
                if page.is_file():
                    html = page.read_text(encoding="utf-8").replace("__SESSION__", str(read_session()))
                    self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                    return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._post()
        except Exception as exc:  # noqa: BLE001 — наружу не отдаём трейсбек
            self._json(500, {"ok": False, "error": f"внутренняя ошибка: {type(exc).__name__}"})

    def _post(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/draft", "/save", "/progress"):
            self._send(404, b"not found", "text/plain")
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._json(415, {"ok": False, "error": "нужен Content-Type: application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"ok": False, "error": "битый Content-Length"})
            return
        if length > MAX_BODY:
            self._json(413, {"ok": False, "error": f"тело больше {MAX_BODY} байт"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"ok": False, "error": f"тело не JSON: {type(exc).__name__}"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "error": "тело должно быть объектом JSON"})
            return

        session = payload.get("session")
        if not isinstance(session, int) or isinstance(session, bool) or session < 0:
            session = read_session()
        raw_answers = payload.get("answers")
        if raw_answers is None:
            answers: dict[str, str] = {}
        elif not isinstance(raw_answers, dict):
            self._json(400, {"ok": False, "error": "answers должен быть объектом {номер: текст}"})
            return
        else:
            answers = {}
            for key, value in raw_answers.items():
                if not isinstance(value, str):
                    self._json(400, {"ok": False,
                                     "error": f"ответ {key!r} должен быть строкой"})
                    return
                answers[str(key)] = value
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        Cfg.answers().mkdir(parents=True, exist_ok=True)

        if path == "/progress":
            # урок или игра: каждый шаг дописывается строкой, флаг входа снимается на финише.
            # Имя страницы — не путь: только буквы, цифры, дефис и подчёркивание.
            page = page_name(payload.get("page"))
            if not page:
                self._json(400, {"ok": False, "error": "page: до 32 символов [a-z0-9_-]"})
                return
            row = {"saved_at": stamp, "session": session,
                   **{k: v for k, v in payload.items() if k not in ("session", "page")}}
            with (Cfg.answers() / f"{page}_{session}.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            done = bool(payload.get("finished"))
            if done:
                (Cfg.study / f"{page}_pending").unlink(missing_ok=True)
            print(f"[{stamp}] {page}: экран {payload.get('screen')} из {payload.get('total')}"
                  f"{', завершено' if done else ''}", flush=True)
            self._json(200, {"ok": True, "stamp": stamp, "finished": done})
            return

        if path == "/draft":
            out = Cfg.answers() / f"block_{session}_draft.json"
            out.write_text(json.dumps({"session": session, "saved_at": stamp, "answers": answers},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
            self._json(200, {"ok": True, "stamp": stamp})
            return

        try:
            info = parse_block(Cfg.current().read_text(encoding="utf-8"))
            title, total_q = info["title"], info["count"]
        except Exception:  # noqa: BLE001
            title, total_q = f"Блок {session}", len(answers)

        order = sorted(answers, key=lambda k: int(k) if str(k).isdigit() else 999)
        body = [title, f"Ответы сохранены {stamp}", ""]
        empty = []
        for key in order:
            text = (answers[key] or "").strip()
            if not text:
                empty.append(key)
                continue
            body.append(f"{key} - {text.replace(chr(10), ' ').strip()}")
            body.append("")
        if empty:
            body.append("Без ответа: " + ", ".join(empty))
            body.append("")
        txt = Cfg.answers() / f"block_{session}_answers.txt"
        txt.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
        js = Cfg.answers() / f"block_{session}_answers.json"
        js.write_text(json.dumps({"session": session, "saved_at": stamp, "title": title,
                                  "answers": answers}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        print("", flush=True)
        print("=" * 60, flush=True)
        print(f"ОТВЕТЫ СОХРАНЕНЫ: {txt}", flush=True)
        print(f"Отвечено {len(order) - len(empty)} из {total_q}; без ответа: "
              f"{', '.join(empty) or 'нет'}", flush=True)
        print("Скажи ассистенту «готово». Окно можно закрыть.", flush=True)
        print("=" * 60, flush=True)
        self._json(200, {"ok": True, "stamp": stamp, "path": str(txt),
                         "answered": len(order) - len(empty), "total": total_q, "empty": empty})


def pick_port(start: int, tries: int = 12) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"Свободного порта {start}-{start + tries - 1} нет")


def main() -> None:
    ap = argparse.ArgumentParser(description="Тренажёр цикла обучения")
    ap.add_argument("--study", default=str(ROOT / "study"), help="папка данных (state.json, current.txt)")
    ap.add_argument("--port", type=int, default=8765, help="первый порт из диапазона 8765..8776")
    ap.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    args = ap.parse_args()

    Cfg.study = Path(args.study).resolve()
    Cfg.open_browser = not args.no_browser
    if not Cfg.current().exists():
        print(f"{Cfg.current()} не найден — блок не подготовлен.")
        sys.exit(1)

    info = parse_block(Cfg.current().read_text(encoding="utf-8"))
    port = pick_port(args.port)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    page = pending_page()
    url = f"http://127.0.0.1:{port}/" + page
    print(f"Тренажёр: {info['title']}")
    print(f"Сессия {read_session()}, вопросов {info['count']}.")
    if page:
        print(f"Сначала {page}: носитель идёт первым экраном, блок — после него.")
    print(f"Адрес: {url}")
    print("Ответы пишутся в study/answers/. Закрыть — Ctrl+C или это окно.")
    if Cfg.open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Тренажёр остановлен.")


if __name__ == "__main__":
    main()
