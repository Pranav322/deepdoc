"""On-the-fly polyglot fixture generator for scale tests.

Used by test_persistent_index.py (Slice 2) and test_scale.py (Slice 8).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Sequence

TEMPLATES = {
    "py": textwrap.dedent("""\
        def {name}_{i}(value: int) -> int:
            \"\"\"Processing function {i}.\"\"\"
            return value * 2


        class {Name}{i}:
            def __init__(self, data):
                self.data = data

            def process(self):
                return self.data
    """),
    "ts": textwrap.dedent("""\
        export function {name}{i}(value: number): number {{
            return value * 2;
        }}

        export class {Name}{i} {{
            data: any;
            constructor(data: any) {{
                this.data = data;
            }}
            process(): any {{
                return this.data;
            }}
        }}
    """),
    "go": textwrap.dedent("""\
        package src

        func {Name}{i}(value int) int {{
            return value * 2
        }}

        type {Name}{i}Model struct {{
            Data string
        }}
    """),
    "java": textwrap.dedent("""\
        package src;

        public class {Name}{i} {{
            private String data;

            public {Name}{i}(String data) {{
                this.data = data;
            }}

            public int process(int value) {{
                return value * 2;
            }}
        }}
    """),
    "rs": textwrap.dedent("""\
        pub struct {Name}{i} {{
            data: String,
        }}

        pub fn {name}_{i}(value: i32) -> i32 {{
            value * 2
        }}
    """),
    "rb": textwrap.dedent("""\
        class {Name}{i}
          def initialize(data)
            @data = data
          end

          def process(value)
            value * 2
          end
        end
    """),
}

NAMES = [
    "process", "handle", "compute", "resolve", "validate",
    "transform", "execute", "fetch", "aggregate", "normalize",
    "convert", "parse", "merge", "filter", "dispatch",
]

UNSUPPORTED_CONTENT = "This is a file with an unsupported extension — inventory only.\n"


def generate_files(
    target_dir: Path,
    distributions: dict[str, int],
    *,
    subdir: str = "src",
) -> int:
    """Generate a polyglot repo with realistic source files.

    Args:
        target_dir: Root directory for generated files.
        distributions: Mapping of extension → file count.
        subdir: Subdirectory within target_dir (default "src").

    Returns:
        Total number of files generated.
    """
    src = target_dir / subdir
    total = 0

    for ext, count in distributions.items():
        d = src / ext
        d.mkdir(parents=True, exist_ok=True)
        name_list = NAMES

        if ext in TEMPLATES:
            tpl = TEMPLATES[ext]
            for i in range(count):
                name = name_list[i % len(name_list)]
                (d / f"{name}_{i}.{ext}").write_text(
                    tpl.format(name=name, Name=name.capitalize(), i=i)
                )
        elif ext == "foo":
            for i in range(count):
                (d / f"config_{i}.{ext}").write_text(UNSUPPORTED_CONTENT)
        elif ext == "noext":
            for i in range(count):
                (d / f"README_{i}").write_text("Extensionless file — inventory only\n")
        else:
            for i in range(count):
                (d / f"file_{i}.{ext}").write_text(f"// {ext} file {i}\n")
        total += count

    return total


def generate_5k_files(tmp_root: Path) -> None:
    """Generate ~5000 files (Slice 2 memory test fixture)."""
    generate_files(
        tmp_root,
        {"py": 1667, "ts": 1667, "go": 1666},
    )


def generate_50k_files(tmp_root: Path) -> None:
    """Generate ~55000 files (Slice 8 scale test fixture)."""
    generate_files(
        tmp_root,
        {
            "py": 17000,
            "ts": 17000,
            "go": 16000,
            "java": 2000,
            "rs": 2000,
            "rb": 500,
            "foo": 500,
            "noext": 100,
        },
    )


__all__ = ["generate_files", "generate_5k_files", "generate_50k_files", "TEMPLATES", "NAMES"]