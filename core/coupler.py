"""Couplers (acopladores mecánicos roscados) en los extremos de una barra.

Una barra puede llevar un coupler en cada extremo que **no termine en gancho**. Hay dos tipos, según la
rosca que se labra en la barra:

* ``short`` — **rosca corta**: la barra se enrosca en el coupler hasta su centro.
* ``long``  — **rosca larga**: rosca extendida para correr el coupler sobre la barra (empalmes con contratuerca).

El coupler es un accesorio: la longitud de corte **no cambia** (las cotas llegan hasta el extremo de la
barra y la rosca se labra sobre esa longitud); se cuenta por tipo y diámetro en el resumen. Si su proveedor
exige un sobrante por rosca o por forja del extremo, súmelo a la cota del tramo.
"""

from __future__ import annotations

from collections.abc import Iterable

COUPLER_NONE = "none"
COUPLER_SHORT = "short"
COUPLER_LONG = "long"

COUPLER_CHOICES = ((COUPLER_NONE, "Sin coupler"), (COUPLER_SHORT, "Rosca corta"), (COUPLER_LONG, "Rosca larga"))
COUPLER_NAMES = {COUPLER_SHORT: "rosca corta", COUPLER_LONG: "rosca larga"}
COUPLER_CODES = {COUPLER_SHORT: "RC", COUPLER_LONG: "RL"}  # rótulo corto del dibujo
COUPLER_ORDER = (COUPLER_SHORT, COUPLER_LONG)


def coupler_text(kinds: Iterable[str]) -> str:
    """Couplers de una barra en texto: ``"rosca corta"``, ``"2 × rosca corta"`` o ``"rosca corta + rosca larga"``."""
    kinds = [k for k in kinds if k in COUPLER_NAMES]
    if not kinds:
        return ""
    if len(set(kinds)) == 1:
        name = COUPLER_NAMES[kinds[0]]
        return name if len(kinds) == 1 else f"{len(kinds)} × {name}"
    return " + ".join(COUPLER_NAMES[k] for k in kinds)


def coupler_label(kind: str) -> str:
    """Nombre de un tipo de coupler con su rótulo del dibujo: ``"Rosca corta (RC)"``."""
    return f"{COUPLER_NAMES[kind].capitalize()} ({COUPLER_CODES[kind]})"


def coupler_legend(kinds: Iterable[str]) -> str:
    """Leyenda de los rótulos de coupler usados, para el encabezado de la planilla (vacía si no hay couplers)."""
    present = set(kinds)
    used = [k for k in COUPLER_ORDER if k in present]
    if not used:
        return ""
    return " · " + ", ".join(f"{COUPLER_CODES[k]} = coupler de {COUPLER_NAMES[k]}" for k in used)
