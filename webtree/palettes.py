"""Master 16-color palette, planet color schemes, and size tiers."""

MASTER = [
    "#000000",
    "#1d2b53",
    "#7e2553",
    "#008751",
    "#ab5236",
    "#5f574f",
    "#c2c3c7",
    "#fff1e8",
    "#ff004d",
    "#ffa300",
    "#ffec27",
    "#00e436",
    "#29adff",
    "#83769c",
    "#ff77a8",
    "#ffccaa",
]

SCHEMES: dict[str, dict] = {
    "green-blue": {"name": "Green + blue", "colors": [11, 12, 3]},
    "red-orange": {"name": "Red + orange", "colors": [8, 9, 4]},
    "orange-peach": {"name": "Orange + peach", "colors": [9, 15, 4]},
    "red-purple": {"name": "Red + purple", "colors": [8, 13, 2]},
    "brown-orange": {"name": "Brown + orange", "colors": [4, 9, 5]},
    "blue-navy": {"name": "Blue + navy", "colors": [12, 1, 6]},
    "pink-purple": {"name": "Pink + purple", "colors": [14, 13, 2]},
    "yellow-green": {"name": "Yellow + green", "colors": [10, 11, 3]},
    "grey-white": {"name": "Grey + white", "colors": [6, 7, 5]},
}

TIERS = [
    {"tier": 1, "name": "mars", "max_pct": 25.0, "default_scheme": "red-orange"},
    {"tier": 2, "name": "earth", "max_pct": 60.0, "default_scheme": "green-blue"},
    {"tier": 3, "name": "jupiter", "max_pct": float("inf"), "default_scheme": "orange-peach"},
]

ANSI16 = [
    "#000000",
    "#800000",
    "#008000",
    "#808000",
    "#000080",
    "#800080",
    "#008080",
    "#c0c0c0",
    "#808080",
    "#ff0000",
    "#00ff00",
    "#ffff00",
    "#0000ff",
    "#ff00ff",
    "#00ffff",
    "#ffffff",
]


def tier_for(context_pct: float) -> dict:
    """Size tier for a context-window percentage."""
    return next(t for t in TIERS if context_pct < t["max_pct"])


def scheme_colors(scheme_id: str | None, tier_name: str) -> list[str]:
    """Hex colors for a scheme, falling back to the tier default."""
    default = next(t["default_scheme"] for t in TIERS if t["name"] == tier_name)
    scheme = SCHEMES.get(scheme_id or "") or SCHEMES[default]
    return [MASTER[i] for i in scheme["colors"]]


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def ansi_nearest(hex_color: str) -> int:
    """Index of the nearest standard terminal color."""
    r, g, b = _rgb(hex_color)
    return min(range(16), key=lambda i: sum((x - y) ** 2 for x, y in zip((r, g, b), _rgb(ANSI16[i]))))
