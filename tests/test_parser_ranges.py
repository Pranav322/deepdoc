from __future__ import annotations

from deepdoc.parser.base import Symbol
from deepdoc.parser.php_parser import _extract_laravel_routes
from deepdoc.parser.python_parser import _extract_module_constants
from deepdoc.scanner import _build_clusters_from_llm


def test_symbol_normalized_range_falls_back_to_single_line() -> None:
    symbol = Symbol(
        name="LOGIN_HANDLER",
        kind="constant",
        signature="LOGIN_HANDLER = build_handler()",
        start_line=42,
        end_line=0,
    )

    assert symbol.has_known_range() is False
    assert symbol.normalized_range() == (42, 42)


def test_python_module_constants_get_single_line_end_ranges() -> None:
    symbols: list[Symbol] = []

    _extract_module_constants(
        "LOGIN_HANDLER = build_handler()\nclass Service:\n    pass\n",
        symbols,
    )

    assert len(symbols) == 1
    assert symbols[0].start_line == 1
    assert symbols[0].end_line == 1


def test_php_laravel_routes_get_single_line_end_ranges() -> None:
    symbols = _extract_laravel_routes(
        "Route::post('/orders/sync', [SyncController::class, 'run'])->middleware(['auth']);\n"
    )

    assert len(symbols) == 1
    assert symbols[0].start_line == 1
    assert symbols[0].end_line == 1


def test_cluster_building_normalizes_missing_symbol_end_lines() -> None:
    symbols = [
        Symbol(
            name="LOGIN_HANDLER",
            kind="constant",
            signature="LOGIN_HANDLER = build_handler()",
            start_line=120,
            end_line=0,
        )
    ]

    clusters = _build_clusters_from_llm(
        {
            "clusters": [
                {
                    "cluster_name": "handlers",
                    "description": "Handler constants",
                    "symbols": ["LOGIN_HANDLER"],
                }
            ]
        },
        symbols,
    )

    assert len(clusters) == 1
    assert clusters[0].line_ranges == [(120, 120)]
