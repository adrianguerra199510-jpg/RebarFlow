"""Roscas para acoplador (acople mecánico roscado) en los extremos de una barra.

El **acoplador es una sola pieza**; lo que cambia es la **rosca que se labra en cada extremo de barra**, que solo puede
ir en un extremo que **no termine en gancho**:

* ``short`` — **rosca corta**: la barra se enrosca en el acoplador hasta su centro.
* ``long``  — **rosca larga**: rosca extendida para correr el acoplador sobre la barra (empalmes con contratuerca).

Lo normal es que una unión lleve rosca larga en un lado y corta en el otro, pero también hay corta + corta y larga + larga.
El acoplador es un accesorio: la longitud de corte **no cambia** (las cotas llegan hasta el extremo de la barra y la
rosca se labra sobre esa longitud). En el resumen se cuentan las roscas por tipo y diámetro, y los acopladores (cada uno
junta dos extremos roscados). Si su proveedor exige un sobrante por rosca o por forja del extremo, súmelo a la cota.
"""

from __future__ import annotations

from collections.abc import Iterable

COUPLER_NONE = "none"
COUPLER_SHORT = "short"
COUPLER_LONG = "long"

COUPLER_CHOICES = ((COUPLER_NONE, "Sin rosca"), (COUPLER_SHORT, "Rosca corta"), (COUPLER_LONG, "Rosca larga"))
COUPLER_NAMES = {COUPLER_SHORT: "rosca corta", COUPLER_LONG: "rosca larga"}
COUPLER_CODES = {COUPLER_SHORT: "RC", COUPLER_LONG: "RL"}  # rótulo corto del dibujo
COUPLER_ORDER = (COUPLER_SHORT, COUPLER_LONG)


def coupler_text(kinds: Iterable[str]) -> str:
    """Roscas de una barra en texto: ``"rosca corta"``, ``"2 × rosca corta"`` o ``"16 × rosca larga + 16 × rosca corta"``."""
    counts: dict[str, int] = {}
    for kind in kinds:
        if kind in COUPLER_NAMES:
            counts[kind] = counts.get(kind, 0) + 1
    return " + ".join(COUPLER_NAMES[kind] if n == 1 else f"{n} × {COUPLER_NAMES[kind]}" for kind, n in counts.items())


def coupler_label(kind: str) -> str:
    """Nombre de un tipo de rosca con su rótulo del dibujo: ``"Rosca corta (RC)"``."""
    return f"{COUPLER_NAMES[kind].capitalize()} ({COUPLER_CODES[kind]})"


def coupler_legend(kinds: Iterable[str]) -> str:
    """Leyenda de los rótulos de rosca usados, para el encabezado de la planilla (vacía si no hay roscas)."""
    present = set(kinds)
    used = [k for k in COUPLER_ORDER if k in present]
    if not used:
        return ""
    return " · " + ", ".join(f"{COUPLER_CODES[k]} = {COUPLER_NAMES[k]}" for k in used)


def coupler_count(thread_ends: int) -> int:
    """Acopladores que hacen falta para ``thread_ends`` extremos roscados: cada acoplador junta dos (hacia arriba)."""
    return (thread_ends + 1) // 2
