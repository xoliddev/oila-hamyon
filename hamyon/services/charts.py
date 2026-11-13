"""Hisobot diagrammalari (PNG). matplotlib bloklovchi bo'lgani uchun alohida oqimda chiziladi."""
from __future__ import annotations

import asyncio
import io
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from hamyon.core import dates  # noqa: E402
from hamyon.core.money import fmt_number  # noqa: E402
from hamyon.services.reports import Agg  # noqa: E402

PALETTE = ["#2E7D6B", "#E07A5F", "#3D5A80", "#F2CC8F", "#81B29A", "#9C6644", "#6D597A",
           "#E9C46A", "#457B9D", "#B56576", "#A8DADC", "#8D99AE"]
BG = "#FBFAF7"
INK = "#2B2D42"
MUTED = "#8D99AE"


def _short_money(minor: int) -> str:
    som = minor / 100
    if som >= 1_000_000:
        return f"{som / 1_000_000:.1f} mln".replace(".0 ", " ").replace(".", ",")
    if som >= 1_000:
        return f"{som / 1_000:.0f} ming"
    return f"{som:.0f}"


def _render(agg: Agg, title: str) -> bytes:
    cats = sorted((c for c in agg.by_category.values() if c["kind"] == "expense"), key=lambda c: -c["amount"])
    if len(cats) > 7:
        other = sum(c["amount"] for c in cats[6:])
        cats = cats[:6] + [{"name": "Boshqalar", "amount": other}]

    fig = plt.figure(figsize=(9, 10.5), dpi=110, facecolor=BG)
    fig.suptitle(title, fontsize=17, fontweight="bold", color=INK, y=0.975)
    fig.text(0.5, 0.935, f"Chiqim: {fmt_number(agg.expense)} so'm    ·    Kirim: {fmt_number(agg.income)} so'm",
             ha="center", fontsize=11.5, color=MUTED)

    # --- 1. Kategoriyalar donut
    ax1 = fig.add_axes([0.05, 0.42, 0.9, 0.48])
    ax1.set_facecolor(BG)
    if cats:
        values = [c["amount"] for c in cats]
        wedges, _ = ax1.pie(values, colors=PALETTE[: len(values)], startangle=90, counterclock=False,
                            wedgeprops={"width": 0.38, "edgecolor": BG, "linewidth": 2})
        ax1.text(0, 0.06, _short_money(agg.expense), ha="center", va="center", fontsize=19, fontweight="bold",
                 color=INK)
        ax1.text(0, -0.14, "so'm chiqim", ha="center", va="center", fontsize=10, color=MUTED)
        labels = [f"{c['name']}  —  {fmt_number(c['amount'])}  ({c['amount'] * 100 / agg.expense:.0f}%)"
                  for c in cats]
        ax1.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=False, fontsize=10,
                   labelcolor=INK)
        ax1.set_position([0.02, 0.44, 0.44, 0.44])
    else:
        ax1.text(0.5, 0.5, "Chiqim yo'q", ha="center", va="center", fontsize=14, color=MUTED)
        ax1.axis("off")

    # --- 2. Kunlik chiqim ustunlari
    ax2 = fig.add_axes([0.1, 0.07, 0.85, 0.27])
    ax2.set_facecolor(BG)
    days: list[date] = []
    d = agg.start
    while d <= agg.end:
        days.append(d)
        d += timedelta(days=1)
    values = [agg.by_day.get(x.isoformat(), 0) / 100 for x in days]
    colors = ["#E07A5F" if x.weekday() >= 5 else "#3D5A80" for x in days]
    ax2.bar(range(len(days)), values, color=colors, width=0.72)
    if agg.expense and agg.days > 1:
        avg = agg.daily_avg / 100
        ax2.axhline(avg, color="#2E7D6B", linestyle="--", linewidth=1.2)
        ax2.text(-0.4, avg, f"o'rtacha {_short_money(agg.daily_avg)}", va="bottom", ha="left",
                 fontsize=9, color="#2E7D6B",
                 bbox={"facecolor": BG, "edgecolor": "none", "pad": 1.5})
    step = max(1, len(days) // 12)
    ax2.set_xticks(range(0, len(days), step))
    ax2.set_xticklabels([f"{x.day}" for x in days[::step]], fontsize=9, color=MUTED)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _short_money(int(v * 100))))
    ax2.tick_params(axis="y", labelsize=9, colors=MUTED)
    for side in ("top", "right", "left"):
        ax2.spines[side].set_visible(False)
    ax2.spines["bottom"].set_color("#D9D9D9")
    ax2.grid(axis="y", color="#ECECEC", linewidth=0.8)
    ax2.set_axisbelow(True)
    ax2.set_title("Kunlar bo'yicha chiqim (qizil — dam olish kunlari)", fontsize=11, color=INK, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


async def report_chart(agg: Agg, title: str | None = None) -> bytes:
    title = title or dates.fmt_range(agg.start, agg.end)
    return await asyncio.to_thread(_render, agg, title)
