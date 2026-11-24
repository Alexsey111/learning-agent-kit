#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Независимый расчёт чисел блока 1: тензоры, суммы по осям, matmul, broadcasting, flatten.

Считает не «как numpy», а по определениям на чистых списках: форма — кортеж длин осей,
sum(axis=k) убирает ось k, A @ B = сумма произведений по внутренней оси, broadcasting
растягивает ось длины 1 и только её. Поэтому это оракул, а не ещё один источник тех же
ошибок: если я в ключе написал 16 вместо 11, здесь получится 11.

Запуск:  python oracle/tensors_oracle.py
Печатает по строке на каждое число ключа, чтобы гейт numberscheck.py мог сверить обе стороны.
"""
from __future__ import annotations

Shape = tuple[int, ...]


def shape(x: list) -> Shape:
    if isinstance(x, list):
        return (len(x),) + (shape(x[0]) if x else ())
    return ()


def build(dims: Shape, start: int = 1) -> list:
    """Плотный тензор с числами 1..N по порядку — ровно такая сцена, как в уроке."""
    if len(dims) == 1:
        return list(range(start, start + dims[0]))
    step = 1
    for d in dims[1:]:
        step *= d
    return [build(dims[1:], start + i * step) for i in range(dims[0])]


def flatten(x: list) -> list:
    if isinstance(x, list):
        out: list = []
        for row in x:
            out.extend(flatten(row))
        return out
    return [x]


def sum_axis(x: list, axis: int):
    if axis == 0:
        rows = [flatten(r) if isinstance(r, list) else [r] for r in x]
        return [sum(col) for col in zip(*rows)]
    return [sum(r) if isinstance(r, list) else r for r in x]


def matmul(a: list, b: list) -> list:
    sa, sb = shape(a), shape(b)
    if len(sa) != 2 or len(sb) != 2:
        raise ValueError(f"matmul определён для двух осей: {sa} @ {sb}")
    if sa[1] != sb[0]:
        raise ValueError(f"внутренние оси не совпадают: {sa[1]} против {sb[0]}")
    bt = [[b[i][j] for i in range(sb[0])] for j in range(sb[1])]
    return [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def broadcast_add(a: list, b: list):
    sa, sb = shape(a), shape(b)
    if sa == sb:
        return [[x + y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]
    if len(sa) == 2 and len(sb) == 1:
        if sa[1] != sb[0]:
            raise ValueError(f"последняя ось {sa[1]} против {sb[0]} не растягивается")
        return [[v + b[j] for j, v in enumerate(row)] for row in a]
    if len(sa) == 1 and len(sb) == 1:
        if sa[0] != sb[0]:
            raise ValueError(f"длины {sa[0]} и {sb[0]} не совпадают")
        return [x + y for x, y in zip(a, b)]
    raise ValueError(f"broadcasting {sa} + {sb} не определён")


def linear(x: list, w: list, b: list) -> list:
    return [[sum(v * w[i][j] for i, v in enumerate(row)) + b[j] for j in range(len(w[0]))]
            for row in x]


def relu(x: list) -> list:
    return [max(0.0, v) for v in x] if not isinstance(x[0], list) else [relu(r) for r in x]


def linear1d(x: list, w: list, b: list) -> list:
    """Один вектор без батч-оси: Linear(784, 128) на (784,) даёт (128,), а не (1, 128)."""
    return [sum(v * w[i][j] for i, v in enumerate(x)) + b[j] for j in range(len(w[0]))]


def main() -> int:
    # Сцена ровно та, что в блоке 1: A (2, 3), B (3, 4), c (2,).
    A = build((2, 3))          # [[1, 2, 3], [4, 5, 6]]
    B = build((3, 4))          # [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
    c = build((2,))            # [1, 2]
    print(f"вопрос 1, shape x: {shape(A)}")
    print(f"вопрос 1, sum(axis=0): {sum_axis(A, 0)}")
    print(f"вопрос 1, sum(axis=1): {sum_axis(A, 1)}")
    print(f"вопрос 1, sum(): {sum(flatten(A))}")
    print(f"вопрос 2, shape A @ B: {shape(matmul(A, B))}")
    print(f"вопрос 2, A @ B: {matmul(A, B)}")
    print("вопрос 2, B @ A: ", end="")
    try:
        matmul(B, A)
        print("умножилось")
    except ValueError as exc:
        print(f"ошибка, {exc}")
    print("вопрос 2, A + c: ", end="")
    try:
        print(f"сложилось, {broadcast_add(A, c)}")
    except ValueError as exc:
        print(f"ошибка, {exc}")
    print(f"вопрос 2, A + c при c = (3,): {broadcast_add(A, build((3,)))}")
    batch = [build((28, 28)) for _ in range(32)]
    flat = [flatten(sample) for sample in batch]
    print(f"вопрос 3, shape (32, 28, 28) после flatten: {shape(flat)}")
    w = [[1] * 128 for _ in range(784)]
    b128 = [0] * 128
    print(f"вопрос 3, shape на выходе Linear(784, 128) на батче: {shape(linear(flat, w, b128))}")
    print(f"вопрос 3, shape при подаче (784,): {shape(linear1d(flatten(batch[0]), w, b128))}")
    print(f"вопрос 3, внутренняя ось умножения: {784}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
