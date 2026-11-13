"""Pul bilan ishlash: hamma summalar butun sonda, eng kichik birlikda (tiyin/sent) saqlanadi.

AI hech qachon yakuniy summani o'zi hisoblamaydi - u faqat ifoda beradi ("2*9500"),
uni esa shu yerda Decimal yordamida aniq hisoblaymiz. Float umuman ishlatilmaydi.
"""
from __future__ import annotations

import ast
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MINOR = 100  # 1 so'm = 100 tiyin, 1 $ = 100 sent ...

CURRENCIES: dict[str, dict[str, str]] = {
    "UZS": {"sign": "so'm", "name": "so'm"},
    "USD": {"sign": "$", "name": "dollar"},
    "EUR": {"sign": "€", "name": "yevro"},
    "RUB": {"sign": "rubl", "name": "rubl"},
}

# AI xato qilib so'z qoldirsa ham tushunish uchun xavfsizlik to'ri
_WORD_MULTIPLIERS = [
    (r"(?:mlrd|milliard|млрд|миллиард)", "*1000000000"),
    (r"(?:mln|million|millon|млн|миллион)", "*1000000"),
    (r"(?:ming|минг|тысяч[аи]?|тыс|k)", "*1000"),
]


class AmountError(ValueError):
    """Summani tushunib bo'lmadi."""


def _normalize_expr(expr: str) -> str:
    s = str(expr).strip().lower()
    s = s.replace("×", "*").replace("x", "*").replace("х", "*").replace("÷", "/").replace("−", "-")
    s = s.replace("so'm", "").replace("сум", "").replace("сўм", "").replace("$", "").replace("€", "")
    # "1 500 000" -> "1500000" (raqamlar orasidagi bo'sh joy - minglik ajratuvchi)
    s = re.sub(r"(?<=\d)[\s  '](?=\d{3}\b)", "", s)
    # "1,5" -> "1.5" (o'nlik vergul); "1,500,000" -> "1500000" (minglik vergul)
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = re.sub(r"(?<=\d),(?=\d)", ".", s)
    for pattern, repl in _WORD_MULTIPLIERS:
        s = re.sub(r"(?<=[\d.)])\s*" + pattern + r"\b", repl, s)
    return s.replace(" ", "")


def eval_amount(expr: str | int | float | None) -> Decimal:
    """Arifmetik ifodani aniq hisoblaydi: '2*9500' -> Decimal('19000')."""
    if expr is None:
        raise AmountError("summa ko'rsatilmagan")
    if isinstance(expr, int):
        return Decimal(expr)
    source = _normalize_expr(str(expr))
    if not source or len(source) > 300:
        raise AmountError(f"summa noto'g'ri: {expr!r}")
    if not re.fullmatch(r"[\d.+\-*/()]+", source):
        raise AmountError(f"summada ruxsat etilmagan belgi bor: {expr!r}")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise AmountError(f"summa ifodasi buzuq: {expr!r}") from exc

    def walk(node: ast.AST, depth: int = 0) -> Decimal:
        if depth > 40:
            raise AmountError("ifoda juda murakkab")
        if isinstance(node, ast.Expression):
            return walk(node.body, depth + 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            text = ast.get_source_segment(source, node) or str(node.value)
            try:
                return Decimal(text)
            except InvalidOperation as exc:
                raise AmountError(f"son noto'g'ri: {text}") from exc
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand, depth + 1)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = walk(node.left, depth + 1), walk(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if right == 0:
                raise AmountError("nolga bo'lish")
            return left / right
        raise AmountError(f"tushunarsiz ifoda: {expr!r}")

    return walk(tree)


def to_minor(value: Decimal | int | str) -> int:
    """Asosiy birlikdan (so'm) tiyinga, yarmini yuqoriga yaxlitlab."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int((d * MINOR).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_minor(minor: int) -> Decimal:
    return Decimal(minor) / MINOR


def parse_minor(expr: str | int | float | None) -> int:
    return to_minor(eval_amount(expr))


def convert_minor(minor: int, rate_from: Decimal | str, rate_to: Decimal | str = "1") -> int:
    """minor (A valyutada) -> B valyutadagi minor. Kurslar asosiy valyutaga nisbatan."""
    value = Decimal(minor) * Decimal(str(rate_from)) / Decimal(str(rate_to))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _group(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return " ".join(out)


def fmt_number(minor: int, always_decimals: bool = False) -> str:
    """12345678 -> '123 456,78'; 1250000 -> '12 500'."""
    sign = "-" if minor < 0 else ""
    minor = abs(int(minor))
    whole, frac = divmod(minor, MINOR)
    text = _group(str(whole))
    if frac or always_decimals:
        text += f",{frac:02d}"
    return sign + text


def fmt(minor: int, currency: str = "UZS", signed: bool = False) -> str:
    """Odam o'qiydigan ko'rinish: '1 250 000 so'm', '12,50 $'."""
    sign_char = ""
    if signed and minor > 0:
        sign_char = "+"
    sign = CURRENCIES.get(currency, {}).get("sign", currency)
    return f"{sign_char}{fmt_number(minor)} {sign}"


def split_proportionally(total: int, weights: list[int]) -> list[int]:
    """total ni og'irliklarga proporsional taqsimlaydi, yig'indi aynan total bo'ladi (eng katta qoldiq usuli)."""
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum == 0:
        base = [0] * len(weights)
        base[0] = total
        return base
    raw = [Decimal(total) * w / weight_sum for w in weights]
    floors = [int(r.to_integral_value(rounding="ROUND_FLOOR")) for r in raw]
    remainder = total - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    step = 1 if remainder >= 0 else -1
    for i in order[: abs(remainder)]:
        floors[i] += step
    return floors


def percent(part: int, whole: int) -> Decimal:
    if not whole:
        return Decimal(0)
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def fmt_percent(value: Decimal, signed: bool = False) -> str:
    text = f"{value:.1f}".replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    if signed and value > 0:
        text = "+" + text
    return text + "%"


def fmt_decimal(value: Decimal | str | None) -> str:
    """Miqdor uchun: Decimal('1.50') -> '1,5'."""
    if value is None:
        return ""
    d = Decimal(str(value)).normalize()
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    neg = whole.startswith("-")
    whole = _group(whole.lstrip("-"))
    return ("-" if neg else "") + whole + ("," + frac if frac else "")
