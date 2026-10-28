# File: scripts/build_design_tokens.py
"""Generate the Instrument design-token artefacts from one JSON source.

Why this exists: the Phase 4 theme (``plans/phase-4-design-reference.md``, Part T) must
reach three consumers -- the web app's CSS, the Plotly charts, and a contrast audit --
without the three drifting apart. ``assets/design-tokens/instrument.json`` is the single
source; this script turns it into

* ``apps/web/src/theme/tokens.css``          CSS custom properties (dark only, decision 5);
* ``apps/web/src/theme/tokens.resolved.json`` flat values + contrast results for the token page;
* ``assets/design-tokens/plotly-template.json`` a Plotly ``layout.template`` (plot well style);
* ``assets/design-tokens/contrast-report.md`` every contrast pair with its ratio.

It also *enforces* accessibility: each pair listed under ``checks`` (plus every region fill
and series colour, computed here) must meet its WCAG ratio, otherwise the script exits
non-zero. The tests in ``tests/assets/test_design_tokens.py`` import this module, so a
token edit that breaks contrast, or a stale generated file, fails the suite.

Region fills follow the "50 % rule" measured on the reference (each category fill is its
key colour at 50 % opacity over the pane); they are computed here, never hand-typed.

Standard library only. Usage::

    python scripts/build_design_tokens.py           # write the four artefacts
    python scripts/build_design_tokens.py --check   # fail if any artefact is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "design-tokens" / "instrument.json"
OUT_CSS = ROOT / "apps" / "web" / "src" / "theme" / "tokens.css"
OUT_RESOLVED = ROOT / "apps" / "web" / "src" / "theme" / "tokens.resolved.json"
OUT_TEMPLATE = ROOT / "assets" / "design-tokens" / "plotly-template.json"
OUT_REPORT = ROOT / "assets" / "design-tokens" / "contrast-report.md"

# Token groups whose entries are ``[value, source, note]`` triples.
GROUPS = (
    "surface",
    "border",
    "scrollbar",
    "text",
    "blue",
    "semantic",
    "focus",
    "mark",
    "size",
    "font",
    "layout",
)

TEXT_MIN = 4.5  # WCAG 1.4.3 for text
GRAPHIC_MIN = 3.0  # WCAG 1.4.11 for graphics / UI components


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def blend(fg: str, bg: str, alpha: float) -> str:
    """``fg`` at ``alpha`` opacity over ``bg``."""
    f, b = hex_to_rgb(fg), hex_to_rgb(bg)
    return rgb_to_hex(tuple(alpha * x + (1 - alpha) * y for x, y in zip(f, b)))


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    r, g, b = (_channel(c) for c in hex_to_rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two ``#rrggbb`` colours."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def load_source(path: Path = SOURCE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def flatten(src: dict) -> dict[str, str]:
    """``{"surface.pane": "#151618", ...}`` for every triple in :data:`GROUPS`."""
    flat: dict[str, str] = {}
    for group in GROUPS:
        for name, token in src[group].items():
            flat[f"{group}.{name}"] = token[0]
    return flat


def validate(src: dict, flat: dict[str, str]) -> None:
    """Reject a source that would silently produce a wrong chart palette.

    Why: ``region.series_order`` becomes both the CSS ``--series-N`` variables and the Plotly
    ``colorway``. A duplicated or missing name would drop or repeat a series colour without any
    contrast check noticing, so the permutation is enforced here.
    """
    keys, order = src["region"]["keys"], src["region"]["series_order"]
    if sorted(order) != sorted(keys):
        raise ValueError("region.series_order must list every region key exactly once")
    refs = [src["region"]["fill_over"]]
    for fg, bg, _minimum in src["checks"]:
        refs += [fg, bg]
    for ref in refs:
        if ref not in flat:
            raise ValueError(f"unknown token {ref!r}")


def region_fills(src: dict, flat: dict[str, str]) -> dict[str, dict[str, str]]:
    """Each region key with its 50 %-over-pane fill (the measured rule)."""
    region = src["region"]
    base = flat[region["fill_over"]]
    out: dict[str, dict[str, str]] = {}
    for name, token in region["keys"].items():
        out[name] = {
            "key": token[0],
            "fill": blend(token[0], base, region["fill_opacity"]),
        }
    return out


def evaluate_checks(
    src: dict, flat: dict[str, str], fills: dict[str, dict[str, str]]
) -> list[dict]:
    """Every contrast pair: the listed ones, then region fills and series colours."""
    results: list[dict] = []

    def add(label: str, fg: str, bg: str, minimum: float) -> None:
        ratio = contrast(fg, bg)
        results.append(
            {
                "pair": label,
                "fg": fg,
                "bg": bg,
                "min": minimum,
                "ratio": round(ratio, 2),
                "pass": ratio >= minimum,
            }
        )

    for fg, bg, minimum in src["checks"]:
        add(f"{fg} on {bg}", flat[fg], flat[bg], minimum)
    for name, pair in fills.items():
        add(
            f"text.primary on region.{name} fill",
            flat["text.primary"],
            pair["fill"],
            TEXT_MIN,
        )
        add(
            f"region.{name} key on surface.pane",
            pair["key"],
            flat["surface.pane"],
            GRAPHIC_MIN,
        )
    for name in src["region"]["series_order"]:
        add(
            f"series {name} on surface.well",
            fills[name]["key"],
            flat["surface.well"],
            GRAPHIC_MIN,
        )
    return results


def failures(results: list[dict]) -> list[dict]:
    return [r for r in results if not r["pass"]]


def _css_name(key: str) -> str:
    return "--" + key.replace(".", "-")


def render_css(
    src: dict, flat: dict[str, str], fills: dict[str, dict[str, str]]
) -> str:
    lines = [
        "/*",
        " * GENERATED by scripts/build_design_tokens.py from assets/design-tokens/instrument.json.",
        " * Do not edit by hand: edit the JSON and re-run the script.",
        " *",
        " * Instrument theme (Phase 4): C6 layout and colours, dark only. Sizes are in rem so",
        " * browser zoom scales the whole workbench; one row-height variable (--size-row).",
        " * Region fills are the key colour at 50 % over the pane, precomputed here.",
        " */",
        "",
        ":root {",
        f"  color-scheme: {src['color_scheme']};",
    ]
    for group in GROUPS:
        lines.append("")
        lines.append(f"  /* {group} */")
        for name in src[group]:
            lines.append(
                f"  {_css_name(f'{group}.{name}')}: {flat[f'{group}.{name}']};"
            )
    lines += ["", "  /* region key colours and 50 % fills */"]
    for name, pair in fills.items():
        lines.append(f"  --region-{name}: {pair['key']};")
        lines.append(f"  --region-{name}-fill: {pair['fill']};")
    lines += ["", "  /* chart series order */"]
    for i, name in enumerate(src["region"]["series_order"], start=1):
        lines.append(f"  --series-{i}: var(--region-{name});")
    lines += ["}", ""]
    return "\n".join(lines)


def render_template(
    src: dict, flat: dict[str, str], fills: dict[str, dict[str, str]]
) -> str:
    mono = flat["font.mono"]
    axis = {
        "gridcolor": flat["surface.well-frame"],
        "griddash": "dot",
        "gridwidth": 1,
        "zeroline": False,
        "linecolor": flat["scrollbar.thumb"],
        "ticks": "outside",
        "tickcolor": flat["scrollbar.thumb"],
        "tickfont": {"family": mono, "size": 11, "color": flat["text.secondary"]},
        "automargin": True,
    }
    well, frame, edge = (
        flat["surface.well"],
        flat["surface.well-frame"],
        flat["scrollbar.thumb"],
    )
    order = src["region"]["series_order"]
    colorway = [fills[n]["key"] for n in order]
    # Tiles that carry their label inside (treemap) use the region *fills*: text.primary is
    # checked at 4.5:1 on every one of them, which none of the bright keys guarantee. Pie slices
    # keep the keys (3:1 against the well) because their labels sit outside.
    area_colorway = [fills[n]["fill"] for n in order]
    # Cell text stays readable at every stop: the heatmap prints its values in the cells and picks
    # white or black per cell, so the scales are built from region *fills* (text.primary is
    # checked at 4.5:1 on each) and the blue key (5.0:1 under white), never the bright keys.
    # Sequential: blue fill to blue key. Diverging: blue and orange (colour-blind safe) fills
    # through the neutral frame.
    sequential = [[0, fills["blue"]["fill"]], [1, fills["blue"]["key"]]]
    diverging = [
        [0, fills["blue"]["fill"]],
        [0.5, frame],
        [1, fills["orange"]["fill"]],
    ]
    tick = {"family": mono, "size": 11, "color": flat["text.secondary"]}
    polar_axis = {
        "gridcolor": frame,
        "griddash": "dot",
        "linecolor": edge,
        "tickfont": tick,
    }
    radial_axis = {
        **polar_axis,
        "angle": 45,  # between two spokes, so its labels do not sit on one
        "tickangle": 0,
        "nticks": 4,
        "showline": False,
    }
    colorbar = {"outlinewidth": 0, "thickness": 8, "tickfont": tick}
    template = {
        "layout": {
            "font": {"family": mono, "size": 11, "color": flat["text.primary"]},
            "paper_bgcolor": flat["surface.well-frame"],
            "plot_bgcolor": flat["surface.well"],
            "colorway": colorway,
            "margin": {"l": 56, "r": 16, "t": 52, "b": 40},
            "xaxis": axis,
            "yaxis": axis,
            "legend": {
                "bgcolor": "rgba(0,0,0,0)",
                "font": {"family": mono, "size": 11, "color": flat["text.secondary"]},
                # One row just above the plot, under the title: below the plot it collides
                # with the x axis title.
                "orientation": "h",
                "x": 0,
                "xanchor": "left",
                "y": 1,
                "yanchor": "bottom",
            },
            "hoverlabel": {
                "bgcolor": flat["surface.chrome"],
                "bordercolor": flat["border.focused"],
                "font": {"family": mono, "size": 11, "color": flat["text.primary"]},
            },
            "title": {
                "x": 0,
                "y": 1,
                "yref": "container",
                "yanchor": "top",
                "pad": {"t": 8},
                "font": {"family": mono, "size": 11, "color": flat["text.primary"]},
            },
            # Pie, treemap and funnel-area traces take their own colourway property.
            "piecolorway": colorway,
            "treemapcolorway": area_colorway,
            "funnelareacolorway": colorway,
            "colorscale": {
                "sequential": sequential,
                "sequentialminus": sequential,
                "diverging": diverging,
            },
            "polar": {
                "bgcolor": well,
                # Leave a row above the circle for the legend and the top axis label.
                "domain": {"y": [0, 0.86]},
                "radialaxis": radial_axis,
                "angularaxis": polar_axis,
            },
            # The mode bar stays visible (WCAG 2.1.1); only its colours change.
            "modebar": {
                "bgcolor": "rgba(0,0,0,0)",
                "color": flat["text.secondary"],
                "activecolor": flat["text.primary"],
            },
        },
        "data": {
            "bar": [{"marker": {"line": {"width": 0}}}],
            "histogram": [{"marker": {"line": {"width": 0}}}],
            "scatter": [{"line": {"width": 1}, "marker": {"size": 5}}],
            "scatterpolar": [{"line": {"width": 1}}],
            "box": [{"line": {"width": 1}}],
            "funnel": [{"marker": {"line": {"width": 0}}}],
            # Tiles and slices are separated by the well colour, not by an outline.
            # Pie labels sit outside, on the well, where text.primary is always readable.
            "pie": [
                {
                    "marker": {"line": {"color": well, "width": 2}},
                    "textposition": "outside",
                    "automargin": True,
                    "textfont": {"color": flat["text.primary"]},
                }
            ],
            "treemap": [
                {
                    "marker": {"line": {"color": well, "width": 1}},
                    "textfont": {"color": flat["text.primary"]},
                }
            ],
            "heatmap": [{"colorbar": colorbar}],
            # Up is the green region, down the red one, the total the first series colour; the
            # step direction is also its height, so colour is never the only channel.
            "waterfall": [
                {
                    "increasing": {"marker": {"color": fills["green"]["key"]}},
                    "decreasing": {"marker": {"color": fills["red"]["key"]}},
                    "totals": {"marker": {"color": fills["blue"]["key"]}},
                    "connector": {"line": {"color": edge, "width": 1}},
                }
            ],
            # Up is a hollow candle in the green region, down a solid one in the red: the body's
            # fill says which way the price moved as well as its colour, so direction survives
            # colour-blindness and a greyscale print (the waterfall does the same with height).
            # A KPI card: the number in the primary text colour, the change in the green or red
            # region key (the arrow in the delta is the other channel), the title in the quiet text.
            "indicator": [
                {
                    "number": {"font": {"family": mono, "color": flat["text.primary"]}},
                    "delta": {
                        "increasing": {"color": fills["green"]["key"]},
                        "decreasing": {"color": fills["red"]["key"]},
                    },
                    "title": {
                        "font": {
                            "family": mono,
                            "size": 11,
                            "color": flat["text.secondary"],
                        }
                    },
                }
            ],
            "candlestick": [
                {
                    "increasing": {
                        "line": {"color": fills["green"]["key"], "width": 1},
                        "fillcolor": "rgba(0,0,0,0)",
                    },
                    "decreasing": {
                        "line": {"color": fills["red"]["key"], "width": 1},
                        "fillcolor": fills["red"]["key"],
                    },
                }
            ],
        },
    }
    return json.dumps(template, indent=2) + "\n"


def render_resolved(
    src: dict,
    flat: dict[str, str],
    fills: dict[str, dict[str, str]],
    results: list[dict],
) -> str:
    sources = {f"{g}.{n}": tok[1] for g in GROUPS for n, tok in src[g].items()}
    doc = {
        "$generated": "scripts/build_design_tokens.py",
        "tokens": flat,
        "sources": sources,
        "region": fills,
        "series_order": src["region"]["series_order"],
        "checks": results,
        "known_weak": [
            {
                "fg": flat[fg],
                "bg": flat[bg],
                "pair": f"{fg} on {bg}",
                "ratio": round(contrast(flat[fg], flat[bg]), 2),
                "why": why,
            }
            for fg, bg, why in src["known_weak"]
        ],
    }
    return json.dumps(doc, indent=2) + "\n"


def render_report(src: dict, flat: dict[str, str], results: list[dict]) -> str:
    lines = [
        "# Instrument contrast report",
        "",
        "Generated by `scripts/build_design_tokens.py` from `assets/design-tokens/instrument.json`.",
        "Text pairs need 4.5 : 1 (WCAG 1.4.3); graphics and UI strokes need 3 : 1 (WCAG 1.4.11).",
        "",
        f"**{sum(r['pass'] for r in results)} of {len(results)} pairs pass.**",
        "",
        "| Pair | Ratio | Min | Result |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['pair']} | {r['ratio']:.2f} | {r['min']} | {'pass' if r['pass'] else 'FAIL'} |"
        )
    lines += [
        "",
        "## Known weak pairs (not asserted)",
        "",
        "| Pair | Ratio | Why it is acceptable |",
        "|---|---|---|",
    ]
    for fg, bg, why in src["known_weak"]:
        lines.append(f"| {fg} on {bg} | {contrast(flat[fg], flat[bg]):.2f} | {why} |")
    lines.append("")
    return "\n".join(lines)


def build(src: dict | None = None) -> tuple[dict[Path, str], list[dict]]:
    """Return ``({output path: content}, contrast results)`` without touching disk."""
    src = src if src is not None else load_source()
    flat = flatten(src)
    validate(src, flat)
    fills = region_fills(src, flat)
    results = evaluate_checks(src, flat, fills)
    outputs = {
        OUT_CSS: render_css(src, flat, fills),
        OUT_RESOLVED: render_resolved(src, flat, fills, results),
        OUT_TEMPLATE: render_template(src, flat, fills),
        OUT_REPORT: render_report(src, flat, results),
    }
    return outputs, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="fail if any artefact is stale"
    )
    args = parser.parse_args(argv)

    try:
        outputs, results = build()
    except ValueError as exc:
        print(f"INVALID TOKEN SOURCE: {exc}", file=sys.stderr)
        return 1
    bad = failures(results)
    for r in bad:
        print(
            f"CONTRAST FAIL {r['pair']}: {r['ratio']:.2f} < {r['min']}", file=sys.stderr
        )
    if bad:
        return 1

    stale = [
        p
        for p, text in outputs.items()
        if not p.is_file() or p.read_text(encoding="utf-8") != text
    ]
    if args.check:
        for p in stale:
            print(f"STALE {p.relative_to(ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    for path, text in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")
    print(f"{len(results)} contrast pairs pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
