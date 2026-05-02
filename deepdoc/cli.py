"""DeepDoc CLI — deepdoc init | generate | update | serve | deploy"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import CONFIG_FILE, DEFAULT_CONFIG, find_config, load_config, save_config

console = Console()
CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 100,
}
_DEPRECATED_VERSION_WARNING_REPOS: set[Path] = set()


# ─────────────────────────────────────────────────────────────────────────────
# CLI group
# ─────────────────────────────────────────────────────────────────────────────


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(__version__, prog_name="deepdoc")
@click.pass_context
def main(ctx: click.Context) -> None:
    """
    Generate, update, preview, and deploy documentation for a repository.

    \b
    Typical workflow:
      1. deepdoc init
      2. deepdoc generate
      3. deepdoc serve
      4. deepdoc update

    Use `deepdoc <command> --help` for examples and next-step guidance.
    """
    _autoload_repo_env(Path.cwd())
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _find_repo_env_file(start: Path) -> Path | None:
    """Walk upward to find the nearest .env file."""
    for directory in [start, *start.parents]:
        candidate = directory / ".env"
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _parse_env_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].strip()
    if "=" not in stripped:
        return None

    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    raw_value = raw_value.strip()
    if not raw_value:
        return key, ""

    try:
        parts = shlex.split(raw_value, posix=True)
        if parts:
            return key, parts[0]
    except ValueError:
        pass

    if (
        len(raw_value) >= 2
        and raw_value[0] == raw_value[-1]
        and raw_value[0] in {"'", '"'}
    ):
        return key, raw_value[1:-1]
    return key, raw_value


def _autoload_repo_env(start: Path) -> Path | None:
    """Load the nearest repo .env file into process env without overriding exports."""
    env_path = _find_repo_env_file(start)
    if env_path is None:
        return None

    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = _parse_env_assignment(line)
            if not parsed:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)
    except OSError:
        return None
    return env_path


# ─────────────────────────────────────────────────────────────────────────────
# init
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Create .deepdoc.yaml for the current repository.")
@click.option(
    "--name",
    default="",
    show_default=False,
    help="Project name shown in the generated docs. Defaults to the current directory name.",
)
@click.option(
    "--description",
    default="",
    show_default=False,
    help="Short project description used in config and site metadata.",
)
@click.option(
    "--provider",
    default="anthropic",
    show_default=True,
    type=click.Choice(["anthropic", "openai", "ollama", "azure"], case_sensitive=False),
    help="LLM provider to configure for the first run.",
)
@click.option(
    "--model",
    default="",
    show_default=False,
    help="Model name to store in config. If omitted, DeepDoc picks a provider-specific default.",
)
@click.option(
    "--output-dir",
    default="docs",
    show_default=True,
    help="Directory where generated Markdown docs will be written.",
)
@click.option(
    "--with-chatbot",
    is_flag=True,
    help="Enable code-and-artifact chatbot scaffolding and indexing in generated repos.",
)
def init(name, description, provider, model, output_dir, with_chatbot):
    """Initialize DeepDoc in the current repository.

    This command creates `.deepdoc.yaml` and fills in sensible defaults for the chosen provider.

    \b
    Examples:
      deepdoc init
      deepdoc init --provider openai --model gpt-4o
      deepdoc init --provider ollama --model ollama/llama3.2
      deepdoc init --output-dir documentation
    """
    cwd = Path.cwd()

    if (cwd / CONFIG_FILE).exists():
        console.print(
            f"[yellow]⚠ {CONFIG_FILE} already exists. Overwrite?[/yellow] (y/N) ",
            end="",
        )
        if input().strip().lower() != "y":
            console.print("[dim]Aborted.[/dim]")
            return

    # Provider defaults
    provider_defaults = {
        "anthropic": ("claude-3-5-sonnet-20241022", "ANTHROPIC_API_KEY"),
        "openai": ("gpt-4o", "OPENAI_API_KEY"),
        "ollama": ("ollama/llama3.2", None),
        "azure": ("azure/gpt-4o", "AZURE_API_KEY"),
    }
    default_model, default_key_env = provider_defaults.get(provider, ("", ""))
    resolved_model = model or default_model

    cfg = dict(DEFAULT_CONFIG)
    cfg["project_name"] = name or cwd.name
    cfg["description"] = description
    cfg["output_dir"] = output_dir
    cfg["llm"]["provider"] = provider
    cfg["llm"]["model"] = resolved_model
    if default_key_env:
        cfg["llm"]["api_key_env"] = default_key_env
    if provider == "ollama":
        cfg["llm"]["base_url"] = "http://localhost:11434"
        cfg["llm"]["api_key_env"] = ""
    if with_chatbot:
        from .chatbot.settings import DEFAULT_CHATBOT_CONFIG

        cfg["chatbot"] = {**DEFAULT_CHATBOT_CONFIG, "enabled": True}

    save_config(cfg, cwd / CONFIG_FILE)

    # Create .gitignore entries for the generated site build artifacts
    _add_gitignore_entries(
        cwd,
        [
            "site/node_modules/",
            "site/.next/",
            "site/.source/",
            "site/out/",
            ".deepdoc/chatbot/",
            "chatbot_backend/.venv/",
            "chatbot_backend/__pycache__/",
            ".deepdoc_manifest.json",
        ],
    )

    next_steps = [
        "  1. Review config:     [bold]deepdoc config show[/bold]",
    ]
    if cfg["llm"]["api_key_env"]:
        next_steps.append(
            f"  2. Set your API key:  [bold]export {cfg['llm']['api_key_env']}=...[/bold]"
        )
        next_steps.append("  3. Generate docs:     [bold]deepdoc generate[/bold]")
        next_steps.append("  4. Preview locally:   [bold]deepdoc serve[/bold]")
    else:
        next_steps.append("  2. Make sure Ollama is running locally")
        next_steps.append("  3. Generate docs:     [bold]deepdoc generate[/bold]")
        next_steps.append("  4. Preview locally:   [bold]deepdoc serve[/bold]")
    if with_chatbot:
        next_steps.append(
            "  5. Set chatbot keys:  [bold]export DEEPDOC_CHAT_API_KEY=... DEEPDOC_EMBED_API_KEY=...[/bold]"
        )

    console.print(
        Panel.fit(
            f"[bold green]✓ DeepDoc initialized![/bold green]\n\n"
            f"Config saved to [cyan]{CONFIG_FILE}[/cyan]\n"
            f"Docs will be generated to [cyan]{output_dir}/[/cyan]\n\n"
            f"[dim]Next steps:[/dim]\n" + "\n".join(next_steps),
            title="DeepDoc",
            border_style="green",
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# generate
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Create docs for the current repository.")
@click.option(
    "--force",
    is_flag=True,
    help="Fully refresh existing DeepDoc-managed docs instead of refusing to overwrite them.",
)
@click.option(
    "--clean",
    is_flag=True,
    help="Delete generated docs and saved DeepDoc state, then rebuild from scratch.",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip the confirmation prompt used by destructive actions such as --clean.",
)
@click.option(
    "--include",
    multiple=True,
    help="Restrict scanning to these glob patterns. Repeat the flag to include multiple roots.",
)
@click.option(
    "--exclude",
    multiple=True,
    help="Add extra glob patterns to exclude for this run. Repeat the flag as needed.",
)
@click.option(
    "--api/--skip-api",
    "include_api",
    default=None,
    help="Include detected API endpoint pages for this run. Use --skip-api to omit grouped API buckets and endpoint details.",
)
@click.option(
    "--deploy",
    is_flag=True,
    help="Run `deepdoc deploy` automatically after a successful generation.",
)
@click.option(
    "--batch-size",
    default=10,
    show_default=True,
    help="How many pages to generate per batch before pausing briefly for rate limits.",
)
@click.option(
    "--max-parallel-workers",
    default=None,
    type=int,
    help="Max concurrent LLM calls for generation, clustering, and decompose. Default: 6.",
)
@click.option(
    "--rate-limit-pause",
    default=None,
    type=float,
    help="Seconds to pause between generation batches. 0 = no pause. Default: 0.5.",
)
def generate(
    force,
    clean,
    yes,
    include,
    exclude,
    include_api,
    deploy,
    batch_size,
    max_parallel_workers,
    rate_limit_pause,
):
    """Generate documentation for the entire codebase.

    \b
    When to use which mode:
      deepdoc generate              First run in a repo
      deepdoc generate --force      Full refresh of existing DeepDoc docs
      deepdoc generate --clean      Wipe docs + saved state, then rebuild

    \b
    Pipeline overview:
      1. Scan       Collect files, symbols, endpoints, and OpenAPI specs
      2. Plan       Build a bucket-based docs plan with the LLM
      3. Generate   Write pages batch-by-batch
      4. API Ref     Stage OpenAPI assets for Fumadocs API pages
      5. Build      Write the generated Fumadocs site scaffold
    """
    cfg = _load_or_exit()
    repo_root = _find_repo_root()
    output_dir = repo_root / cfg.get("output_dir", "docs")
    output_state = _inspect_output_state(repo_root, output_dir)
    effective_force = force or clean

    if clean:
        _confirm_clean(repo_root, output_dir, yes)
        _wipe_deepdoc_output(repo_root, output_dir)
        output_state = _inspect_output_state(repo_root, output_dir)

    if output_state["deepdoc_managed"] and not effective_force:
        raise click.ClickException(
            f"DeepDoc docs already exist in {output_dir}. "
            "Use `deepdoc update` for incremental refresh, "
            "`deepdoc generate --force` for a full refresh, "
            "or `deepdoc generate --clean --yes` to rebuild from scratch."
        )

    if output_state["has_files"] and not output_state["deepdoc_managed"] and not clean:
        raise click.ClickException(
            f"{output_dir} already exists and does not look DeepDoc-managed. "
            "Use a different output directory or run `deepdoc generate --clean --yes` "
            "to replace it explicitly."
        )

    if include:
        cfg["include"] = list(include)
    if exclude:
        cfg["exclude"] = cfg.get("exclude", []) + list(exclude)
    if include_api is not None:
        cfg["include_endpoint_pages"] = include_api
    cfg["batch_size"] = batch_size
    if max_parallel_workers is not None:
        cfg["max_parallel_workers"] = max_parallel_workers
    if rate_limit_pause is not None:
        cfg["rate_limit_pause"] = rate_limit_pause

    console.print(
        Panel.fit(
            f"[bold]Generating docs for [cyan]{cfg.get('project_name') or repo_root.name}[/cyan][/bold]\n"
            f"Provider: [dim]{cfg['llm']['provider']}[/dim]  Model: [dim]{cfg['llm']['model']}[/dim]",
            border_style="blue",
        )
    )

    from .pipeline_v2 import PipelineV2

    pipeline = PipelineV2(repo_root, cfg)
    pipeline.run(force=effective_force, reconcile=force and not clean)

    if deploy:
        ctx = click.get_current_context()
        ctx.invoke(_deploy)


# ─────────────────────────────────────────────────────────────────────────────
# clean
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Remove DeepDoc config, generated output, and saved state.")
@click.option(
    "--yes",
    is_flag=True,
    help="Skip the confirmation prompt before deleting DeepDoc artifacts.",
)
def clean(yes):
    """Reset the current repository to a pre-DeepDoc state.

    This removes `.deepdoc.yaml`, generated docs, the generated site scaffold,
    chatbot backend scaffolding, and saved DeepDoc state files/directories.

    \b
    Examples:
      deepdoc clean
      deepdoc clean --yes
    """
    cfg_path = find_config()
    repo_root = cfg_path.parent if cfg_path else Path.cwd()
    cfg = load_config(cfg_path)
    output_dir = repo_root / cfg.get("output_dir", "docs")
    targets = _cleanup_targets(repo_root, output_dir, include_config=True)

    if not targets:
        console.print(
            "[dim]No DeepDoc config, output, or saved state found to remove.[/dim]"
        )
        return

    _confirm_clean(repo_root, output_dir, yes, include_config=True)
    _wipe_deepdoc_output(repo_root, output_dir, include_config=True)

    console.print(
        "[green]✓ Removed DeepDoc config, generated output, and saved state.[/green]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# update
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Refresh docs after source code changes.")
@click.option(
    "--since",
    default=None,
    help="Git ref to diff against (e.g. HEAD~3, main). "
    "Defaults to the last synced commit.",
)
@click.option(
    "--deploy",
    is_flag=True,
    help="Run `deepdoc deploy` automatically after a successful update.",
)
@click.option(
    "--replan",
    is_flag=True,
    help="Force a full replan even if DeepDoc thinks an incremental update would be enough.",
)
def update(since, deploy, replan):
    """Incrementally update docs for commits newer than the last sync.

    Run `deepdoc generate` once before using this command.

    \b
    Smart update strategy:
      incremental   Regenerate only buckets affected by changed files
      targeted      Replan when new integrations or structures appear
      full replan   Used for large structural changes or when --replan is set

    The strategy is chosen automatically based on the commit diff.
    If no --since is provided, DeepDoc diffs from the commit where docs
    were last fully synced (stored in .deepdoc/state.json).
    """
    cfg = _load_or_exit()
    repo_root = _find_repo_root()

    # Resolve --since: explicit override > saved baseline
    if since is not None:
        console.print(f"[dim]Using explicit --since: {since}[/dim]")
    else:
        from .persistence_v2 import load_sync_state

        sync_state = load_sync_state(repo_root)
        if sync_state and sync_state.get("last_synced_commit"):
            since = sync_state["last_synced_commit"]
            synced_at = sync_state.get("synced_at", "unknown")[:19]
            console.print(
                f"[dim]Diffing from last sync: {since[:10]}... "
                f"(synced at {synced_at})[/dim]"
            )
        else:
            raise click.ClickException(
                "No sync baseline found. Run `deepdoc generate` first, or pass `--since <git-ref>`."
            )

    mode = cfg.get("generation_mode", "feature_buckets")
    if mode == "feature_buckets":
        from .smart_update_v2 import SmartUpdater

        updater = SmartUpdater(repo_root, cfg)
        stats = updater.update(since=since, force_replan=replan)
        count = stats.get("pages_updated", 0)
    else:
        console.print(
            Panel.fit(
                f"[bold]Updating docs[/bold] since [cyan]{since}[/cyan]",
                border_style="blue",
            )
        )
        from .updater_v2 import UpdaterV2

        updater = UpdaterV2(repo_root, cfg)
        count = updater.update(since=since)
        if count > 0:
            console.print(f"\n[bold green]✓ Updated {count} page(s)[/bold green]")
        else:
            console.print("[dim]Nothing to update.[/dim]")

    if deploy and count > 0:
        ctx = click.get_current_context()
        ctx.invoke(_deploy)


# ─────────────────────────────────────────────────────────────────────────────
# status
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Show what DeepDoc has generated and what is stale.")
def status():
    """Show documentation generation status and stale buckets.

    \b
    Use this after `generate` or `update` to see how many pages were produced and
    whether any buckets now look out of date.
    """
    from rich.table import Table

    cfg = _load_or_exit()
    repo_root = _find_repo_root()

    from .persistence_v2 import (
        find_stale_buckets,
        ledger_summary,
        load_generation_ledger,
        load_plan,
    )

    plan = load_plan(repo_root)
    if plan is None or not hasattr(plan, "buckets"):
        console.print(
            "[yellow]No v2 bucket plan found. Run [bold]deepdoc generate[/bold] first.[/yellow]"
        )
        return

    summary = ledger_summary(repo_root)
    console.print(
        Panel.fit(
            f"[bold]Documentation Status[/bold]\n\n"
            f"  Buckets planned:   [cyan]{len(plan.buckets)}[/cyan]\n"
            f"  Pages generated:   [cyan]{summary.get('successful', 0)}[/cyan]\n"
            f"  Pages failed:      [cyan]{summary.get('failed', 0)}[/cyan]\n"
            f"  Total words:       [cyan]{summary.get('total_words', 0):,}[/cyan]\n"
            f"  Total diagrams:    [cyan]{summary.get('total_diagrams', 0)}[/cyan]\n"
            f"  By type:           [cyan]{summary.get('by_bucket_type', {})}[/cyan]",
            border_style="blue",
        )
    )

    output_dir = repo_root / cfg.get("output_dir", "docs")
    stale = find_stale_buckets(plan, repo_root, output_dir=output_dir)
    if stale:
        console.print(f"\n[yellow]⚠ {len(stale)} stale bucket(s):[/yellow]")
        ledger = load_generation_ledger(repo_root)
        t = Table(show_header=True, header_style="bold", box=None)
        t.add_column("Bucket", style="cyan")
        t.add_column("Type")
        t.add_column("Last generated")
        t.add_column("Words", justify="right")
        for slug in stale[:20]:
            b = next((b for b in plan.buckets if b.slug == slug), None)
            rec = ledger.get(slug, {})
            t.add_row(
                b.title if b else slug,
                b.bucket_type if b else "?",
                rec.get("generated_at", "never")[:19] if rec else "never",
                str(rec.get("word_count", 0)) if rec else "0",
            )
        console.print(t)
        console.print(
            "\n[dim]Run [bold]deepdoc update[/bold] to refresh stale pages.[/dim]"
        )
    else:
        console.print("[green]✓ All pages are up-to-date.[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# benchmark
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Benchmark planner quality against a gold manifest catalog.")
@click.option(
    "--catalog",
    type=click.Path(path_type=Path),
    default=None,
    help="JSON catalog containing benchmark cases with repo paths and gold expectations.",
)
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Run a single benchmark case against this local repository path.",
)
@click.option(
    "--gold",
    type=click.Path(path_type=Path),
    default=None,
    help="Gold expectation JSON for --repo mode.",
)
@click.option(
    "--chatbot-eval",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional chatbot evaluation JSON used for combined quality scorecards.",
)
@click.option(
    "--scorecard-out",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional path to write a combined docs/chatbot scorecard JSON.",
)
@click.option(
    "--scorecard-label",
    default="baseline",
    show_default=True,
    help="Label stored in the generated scorecard metadata.",
)
@click.option(
    "--strict-scorecard",
    is_flag=True,
    help="Fail the command if scorecard quality gates do not pass.",
)
@click.option(
    "--generated-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Evaluate generated repo outputs under this directory using `.deepdoc/` artifacts.",
)
@click.option(
    "--artifact-repo",
    "artifact_repos",
    multiple=True,
    type=click.Path(path_type=Path),
    help="Specific generated repo output path(s) to evaluate in artifact mode.",
)
@click.option(
    "--endpoint-sample-limit",
    default=80,
    show_default=True,
    type=click.IntRange(1, 2000),
    help="Maximum endpoint-derived bootstrap chatbot eval cases per repo in artifact mode.",
)
def benchmark(
    catalog: Path | None,
    repo_path: Path | None,
    gold: Path | None,
    chatbot_eval: Path | None,
    scorecard_out: Path | None,
    scorecard_label: str,
    strict_scorecard: bool,
    generated_root: Path | None,
    artifact_repos: tuple[Path, ...],
    endpoint_sample_limit: int,
) -> None:
    """Run benchmark scoring for planner/nav quality."""
    from rich.table import Table

    from .benchmark_v2 import (
        build_artifact_scorecard,
        build_quality_scorecard,
        discover_generated_repo_roots,
        load_catalog,
        load_chatbot_eval_rows,
        run_case,
        save_quality_scorecard,
    )

    artifact_mode = generated_root is not None or bool(artifact_repos)
    cfg = {} if artifact_mode else _load_or_exit()
    if artifact_mode and (catalog or repo_path or gold or chatbot_eval):
        raise click.ClickException(
            "Artifact mode cannot be combined with --catalog/--repo/--gold/--chatbot-eval."
        )

    if artifact_mode:
        targets = [path.expanduser().resolve() for path in artifact_repos]
        if generated_root is not None:
            targets.extend(
                discover_generated_repo_roots(generated_root.expanduser().resolve())
            )
        dedup_targets: list[Path] = []
        seen: set[Path] = set()
        for path in targets:
            if path not in seen:
                seen.add(path)
                dedup_targets.append(path)
        if not dedup_targets:
            raise click.ClickException(
                "No generated repos found for artifact mode. Provide --generated-root or --artifact-repo."
            )

        scorecard = build_artifact_scorecard(
            dedup_targets,
            label=scorecard_label,
            endpoint_sample_limit=endpoint_sample_limit,
        )
        out_path = scorecard_out or (
            _find_repo_root() / ".deepdoc" / "quality_scorecard_artifact.json"
        )
        save_quality_scorecard(out_path, scorecard)

        table = Table(
            title="DeepDoc Artifact Scorecard", show_header=True, header_style="bold"
        )
        table.add_column("Repo", style="cyan")
        table.add_column("Docs", justify="right")
        table.add_column("Chatbot", justify="right")
        table.add_column("Invalid", justify="right")
        table.add_column("Failed", justify="right")
        table.add_column("Eval cases", justify="right")

        for repo_snapshot in scorecard.get("repos", []):
            docs_payload = repo_snapshot.get("docs", {})
            chat_payload = repo_snapshot.get("chatbot", {})
            table.add_row(
                repo_snapshot.get("repo", "unknown"),
                f"{docs_payload.get('completeness_score', 0.0):.2f}",
                f"{chat_payload.get('bootstrap_completeness_score', 0.0):.2f}",
                str(docs_payload.get("pages_invalid", 0)),
                str(docs_payload.get("pages_failed", 0)),
                str(chat_payload.get("bootstrap_eval_cases", 0)),
            )
        console.print(table)

        gates = scorecard["overall"]["gates"]
        gate_status = "pass" if scorecard["overall"]["all_gates_pass"] else "fail"
        failing = [name for name, passed in gates.items() if not passed]
        console.print(
            Panel.fit(
                "[bold]Quality Scorecard[/bold]\n\n"
                f"  Mode:               [cyan]{scorecard.get('mode', 'artifact_proxy')}[/cyan]\n"
                f"  Label:              [cyan]{scorecard['label']}[/cyan]\n"
                f"  Docs completeness:  [cyan]{scorecard['docs']['completeness_score']:.2f}[/cyan]\n"
                f"  Chatbot completeness:[cyan]{scorecard['chatbot']['completeness_score']:.2f}[/cyan]\n"
                f"  Overall score:      [cyan]{scorecard['overall']['completeness_score']:.2f}[/cyan]\n"
                f"  Gates:              [cyan]{gate_status}[/cyan]\n"
                f"  Output:             [cyan]{out_path}[/cyan]"
                + (
                    "\n  Failing gates:      [red]" + ", ".join(failing) + "[/red]"
                    if failing
                    else ""
                ),
                border_style="magenta",
            )
        )

        if strict_scorecard and not scorecard["overall"]["all_gates_pass"]:
            raise click.ClickException(
                "Quality scorecard gates failed. Re-run after improving docs/chatbot metrics."
            )
        return

    if repo_path:
        if gold is None:
            raise click.ClickException("--gold is required when using --repo.")
        cases = [
            {
                "name": repo_path.name,
                "family": "ad_hoc",
                "repo_path": str(repo_path),
                "holdout": False,
                "gold": json.loads(gold.read_text(encoding="utf-8")),
            }
        ]
    else:
        if catalog is None:
            raise click.ClickException("Provide --catalog or use --repo with --gold.")
        cases = load_catalog(catalog)

    table = Table(title="DeepDoc Benchmarks", show_header=True, header_style="bold")
    table.add_column("Case", style="cyan")
    table.add_column("Family")
    table.add_column("Holdout")
    table.add_column("Score", justify="right")
    table.add_column("Notes")

    planner_results = []

    for case in cases:
        repo = Path(case["repo_path"]).expanduser()
        if not repo.exists():
            table.add_row(
                case["name"],
                case.get("family", "other"),
                "yes" if case.get("holdout") else "no",
                "SKIP",
                "repo missing",
            )
            continue
        result = run_case(case, cfg)
        planner_results.append(result)
        table.add_row(
            result.name,
            result.family,
            "yes" if result.holdout else "no",
            f"{result.score:.1f}",
            "; ".join(result.notes[:3]) or "ok",
        )

    console.print(table)

    if chatbot_eval is None and scorecard_out is None and not strict_scorecard:
        return

    chatbot_rows = []
    if chatbot_eval is not None:
        chatbot_rows = load_chatbot_eval_rows(chatbot_eval)
        console.print(
            f"[dim]Loaded {len(chatbot_rows)} chatbot eval case(s) from {chatbot_eval}[/dim]"
        )

    scorecard = build_quality_scorecard(
        planner_results=planner_results,
        chatbot_results=chatbot_rows,
        label=scorecard_label,
    )
    out_path = scorecard_out or (
        _find_repo_root() / ".deepdoc" / "quality_scorecard.json"
    )
    save_quality_scorecard(out_path, scorecard)

    gates = scorecard["overall"]["gates"]
    docs_score = scorecard["docs"]["completeness_score"]
    chatbot_score = scorecard["chatbot"]["completeness_score"]
    overall_score = scorecard["overall"]["completeness_score"]
    gate_status = "pass" if scorecard["overall"]["all_gates_pass"] else "fail"
    failing = [name for name, passed in gates.items() if not passed]

    console.print(
        Panel.fit(
            "[bold]Quality Scorecard[/bold]\n\n"
            f"  Label:              [cyan]{scorecard['label']}[/cyan]\n"
            f"  Docs completeness:  [cyan]{docs_score:.2f}[/cyan]\n"
            f"  Chatbot completeness:[cyan]{chatbot_score:.2f}[/cyan]\n"
            f"  Overall score:      [cyan]{overall_score:.2f}[/cyan]\n"
            f"  Gates:              [cyan]{gate_status}[/cyan]\n"
            f"  Output:             [cyan]{out_path}[/cyan]"
            + (
                "\n  Failing gates:      [red]" + ", ".join(failing) + "[/red]"
                if failing
                else ""
            ),
            border_style="magenta",
        )
    )

    if strict_scorecard and not scorecard["overall"]["all_gates_pass"]:
        raise click.ClickException(
            "Quality scorecard gates failed. Re-run after improving docs/chatbot metrics."
        )


# ─────────────────────────────────────────────────────────────────────────────
# serve
# ─────────────────────────────────────────────────────────────────────────────


@main.command(short_help="Serve the generated docs locally with live reload.")
@click.option(
    "--port",
    default=3000,
    show_default=True,
    help="Port to bind the local Fumadocs development server to.",
)
def serve(port):
    """Preview the generated docs locally with live reload.

    \b
    Run `deepdoc generate` first so the generated Fumadocs app and docs exist.
    Requires Node.js >= 18 to be installed.
    """
    _load_or_exit()
    cfg = _load_or_exit()
    repo_root = _find_repo_root()
    site_dir = repo_root / "site"

    package_json = site_dir / "package.json"
    if not package_json.exists():
        console.print(
            "[red]site/package.json not found. Run [bold]deepdoc generate[/bold] first.[/red]"
        )
        sys.exit(1)

    preview_url = f"http://localhost:{port}"
    console.print(
        f"[bold]Serving docs at [link={preview_url}]{preview_url}[/link][/bold]"
    )
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        backend_proc = None
        next_env = os.environ.copy()
        if cfg.get("chatbot", {}).get("enabled"):
            backend_proc, backend_url = _start_chatbot_backend(repo_root, cfg, port)
            if backend_url:
                next_env["NEXT_PUBLIC_DEEPDOC_CHATBOT_BASE_URL"] = backend_url
        if _site_dependencies_need_install(site_dir):
            console.print("[dim]Installing site dependencies...[/dim]")
            install = subprocess.run(
                ["npm", "install"], cwd=str(site_dir), capture_output=False
            )
            if install.returncode != 0:
                console.print("[red]npm install failed.[/red]")
                sys.exit(1)
            _record_site_dependencies_synced(site_dir)

        # Auto-open browser after a short delay to let Next.js start
        import threading
        import webbrowser

        def _open_browser():
            import time

            time.sleep(3)
            webbrowser.open(preview_url)

        threading.Thread(target=_open_browser, daemon=True).start()

        subprocess.run(
            ["npx", "next", "dev", "--port", str(port)],
            cwd=str(site_dir),
            env=next_env,
        )
    except KeyboardInterrupt:
        pass
    except FileNotFoundError:
        console.print(
            "[red]npm/npx not found. Install Node.js >= 18: https://nodejs.org[/red]"
        )
        sys.exit(1)
    finally:
        if "backend_proc" in locals() and backend_proc is not None:
            backend_proc.terminate()
            try:
                backend_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_proc.kill()


# ─────────────────────────────────────────────────────────────────────────────
# deploy
# ─────────────────────────────────────────────────────────────────────────────


@main.command("deploy", short_help="Deploy the generated docs.")
def _deploy():
    """Deploy the generated documentation.

    \b
    Fumadocs builds a static Next.js export:
      1. Run `deepdoc deploy`
      2. Publish `site/out/` to any static host
    """
    cfg = _load_or_exit()
    repo_root = _find_repo_root()
    site_dir = repo_root / "site"
    output_dir = repo_root / str(cfg.get("output_dir", "docs") or "docs")

    package_json = site_dir / "package.json"
    if not package_json.exists():
        console.print(
            "[red]site/package.json not found. Run [bold]deepdoc generate[/bold] first.[/red]"
        )
        sys.exit(1)

    blockers = _deployment_quality_blockers(repo_root, output_dir)
    if blockers:
        raise click.ClickException(
            "Refusing to deploy docs with unresolved quality issues:\n- "
            + "\n- ".join(blockers)
            + "\nRun `deepdoc generate` again after fixing the generation issues."
        )

    console.print(
        Panel.fit(
            "[bold]Fumadocs Deployment:[/bold]\n\n"
            "1. [bold cyan]Static export:[/bold cyan]\n"
            "   Run: [bold]deepdoc deploy[/bold]\n"
            "   Publish [bold]site/out/[/bold] to any static host\n\n"
            "2. [bold cyan]Suggested hosts:[/bold cyan]\n"
            "   Vercel, Netlify, GitHub Pages, Cloudflare Pages, or any CDN/static server",
            title="Deploy",
            border_style="green",
        )
    )
    if cfg.get("chatbot", {}).get("enabled"):
        console.print(
            "[yellow]Chatbot mode is enabled.[/yellow] Deploy [bold]chatbot_backend/[/bold] "
            "separately on an internal Python host and point [bold]chatbot.backend.base_url[/bold] at it."
        )

    # Offer to run a static build
    console.print("\n[dim]Running static build...[/dim]")
    try:
        if _site_dependencies_need_install(site_dir):
            console.print("[dim]Installing site dependencies...[/dim]")
            install = subprocess.run(
                ["npm", "install"], cwd=str(site_dir), capture_output=False
            )
            if install.returncode != 0:
                console.print("[red]npm install failed.[/red]")
                sys.exit(1)
            _record_site_dependencies_synced(site_dir)

        build_result = subprocess.run(
            ["npx", "next", "build"],
            cwd=str(site_dir),
            capture_output=False,
        )
        if build_result.returncode == 0:
            console.print(
                "[bold green]✓ Build complete! Static files are in site/out/[/bold green]"
            )
        else:
            console.print("[red]Build failed.[/red]")
    except FileNotFoundError:
        console.print(
            "[red]npm/npx not found. Install Node.js >= 18: https://nodejs.org[/red]"
        )
        sys.exit(1)


def _site_dependencies_need_install(site_dir: Path) -> bool:
    """Return True when site dependencies are missing or stale."""
    node_modules = site_dir / "node_modules"
    package_lock = site_dir / "package-lock.json"

    if not node_modules.exists():
        return True
    if not package_lock.exists():
        return True

    try:
        stamp_path = _site_dependency_stamp_path(site_dir)
        if not stamp_path.exists():
            return True

        expected_hash = _site_package_manifest_hash(site_dir)
        stamp_data = json.loads(stamp_path.read_text(encoding="utf-8"))
        return stamp_data.get("package_json_hash") != expected_hash
    except FileNotFoundError:
        return True
    except json.JSONDecodeError:
        return True


def _site_dependency_stamp_path(site_dir: Path) -> Path:
    return site_dir / "node_modules" / ".deepdoc-package-sync.json"


def _site_package_manifest_hash(site_dir: Path) -> str:
    package_json = site_dir / "package.json"
    content = package_json.read_bytes()
    return hashlib.sha256(content).hexdigest()


def _record_site_dependencies_synced(site_dir: Path) -> None:
    stamp_path = _site_dependency_stamp_path(site_dir)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path.write_text(
        json.dumps(
            {
                "package_json_hash": _site_package_manifest_hash(site_dir),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# config show
# ─────────────────────────────────────────────────────────────────────────────


@main.group(
    "config",
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    short_help="Show or edit `.deepdoc.yaml` values.",
)
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """Inspect or update `.deepdoc.yaml` without opening the file manually.

    \b
    Examples:
      deepdoc config show
      deepdoc config set llm.model claude-3-5-sonnet-20241022
      deepdoc config set llm.provider openai
      deepdoc config set output_dir documentation
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@config_cmd.command("show", short_help="Print the current merged config.")
def config_show() -> None:
    """Print the current DeepDoc config in a readable table."""
    cfg_path = find_config()
    if cfg_path is None:
        console.print(
            "[red]No .deepdoc.yaml found. Run [bold]deepdoc init[/bold] first.[/red]"
        )
        sys.exit(1)

    cfg = load_config(cfg_path)
    table = Table(title="DeepDoc Config", show_header=True, header_style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    _flatten_config(cfg, "", table)
    console.print(table)


@config_cmd.command("set", short_help="Update one config value by key path.")
@click.argument("key_path", metavar="KEY.PATH")
@click.argument("value", nargs=-1, metavar="VALUE")
def config_set(key_path: str, value: tuple[str, ...]) -> None:
    """Update one config value.

    \b
    Examples:
      deepdoc config set llm.provider openai
      deepdoc config set llm.model gpt-4o
      deepdoc config set output_dir documentation
      deepdoc config set exclude tests/**,dist/**,build/**
    """
    if not value:
        raise click.UsageError(
            "Please provide a value. Example: deepdoc config set llm.model gpt-4o"
        )

    cfg_path = find_config()
    if cfg_path is None:
        console.print(
            "[red]No .deepdoc.yaml found. Run [bold]deepdoc init[/bold] first.[/red]"
        )
        sys.exit(1)

    cfg = load_config(cfg_path)
    resolved_value = " ".join(value)
    _set_nested(cfg, key_path.split("."), resolved_value)
    save_config(cfg, cfg_path)
    console.print(f"[green]✓ Set [cyan]{key_path}[/cyan] = {resolved_value}[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _load_or_exit() -> dict:
    cfg_path = find_config()
    if cfg_path is None:
        console.print(
            "[red]No .deepdoc.yaml found. Run [bold]deepdoc init[/bold] first.[/red]"
        )
        sys.exit(1)
    cfg = load_config(cfg_path)
    _warn_if_deprecated_generated_version(cfg, cfg_path.parent)
    return cfg


def _warn_if_deprecated_generated_version(cfg: dict, repo_root: Path) -> None:
    warning_cfg = (
        cfg.get("compatibility", {}).get("deprecated_version_warning", {})
        if isinstance(cfg.get("compatibility"), dict)
        else {}
    )
    if not warning_cfg.get("enabled", True):
        return

    minimum_version = str(warning_cfg.get("minimum_version") or "1.0.0")
    generated_version = _detect_generated_deepdoc_version(
        repo_root, repo_root / str(cfg.get("output_dir", "docs") or "docs")
    )
    if generated_version is None:
        return
    if _version_tuple(generated_version) >= _version_tuple(minimum_version):
        return

    resolved_root = repo_root.resolve()
    if resolved_root in _DEPRECATED_VERSION_WARNING_REPOS:
        return
    _DEPRECATED_VERSION_WARNING_REPOS.add(resolved_root)

    upgrade_command = str(
        warning_cfg.get("upgrade_command")
        or "python3 -m pip install --upgrade deepdoc"
    )
    console.print(
        Panel.fit(
            "[bold yellow]DeepDoc upgrade recommended[/bold yellow]\n\n"
            f"This repository has generated docs from DeepDoc [bold]{generated_version}[/bold], "
            f"which is older than the supported baseline [bold]{minimum_version}[/bold].\n"
            "Upgrade the CLI before generating or updating docs:\n\n"
            f"[bold]{upgrade_command}[/bold]\n\n"
            "To change or disable this warning, update "
            "`compatibility.deprecated_version_warning.*` in `.deepdoc.yaml`.",
            border_style="yellow",
        )
    )


def _detect_generated_deepdoc_version(repo_root: Path, output_dir: Path) -> str | None:
    candidates = [output_dir]
    docs_dir = repo_root / "docs"
    if docs_dir != output_dir:
        candidates.append(docs_dir)

    for directory in candidates:
        if not directory.exists():
            continue
        for doc_path in sorted(directory.rglob("*.mdx")):
            try:
                content = doc_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = re.search(
                r"^deepdoc_generated_version:\s*[\"']?([^\"'\n]+)[\"']?\s*$",
                content,
                flags=re.MULTILINE,
            )
            if match:
                return match.group(1).strip()
    return None


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _find_repo_root() -> Path:
    """Find the directory containing .deepdoc.yaml."""
    cfg_path = find_config()
    return cfg_path.parent if cfg_path else Path.cwd()


def _inspect_output_state(repo_root: Path, output_dir: Path) -> dict[str, bool]:
    has_files = output_dir.exists() and any(output_dir.iterdir())
    markers = [
        output_dir / ".deepdoc_manifest.json",
        repo_root / ".deepdoc" / "plan.json",
        repo_root / ".deepdoc" / "ledger.json",
        repo_root / ".deepdoc_plan.json",
        repo_root / ".deepdoc_file_map.json",
    ]
    return {
        "has_files": has_files,
        "deepdoc_managed": any(marker.exists() for marker in markers),
    }


def _cleanup_targets(
    repo_root: Path, output_dir: Path, include_config: bool = False
) -> list[Path]:
    targets: list[Path] = []
    if output_dir.exists():
        targets.append(output_dir)

    for path in (
        repo_root / ".deepdoc",
        repo_root / "site",
        repo_root / "chatbot_backend",
        repo_root / ".deepdoc_plan.json",
        repo_root / ".deepdoc_file_map.json",
    ):
        if path.exists():
            targets.append(path)

    if include_config:
        cfg_path = repo_root / CONFIG_FILE
        if cfg_path.exists():
            targets.append(cfg_path)

    return targets


def _confirm_clean(
    repo_root: Path,
    output_dir: Path,
    yes: bool,
    include_config: bool = False,
) -> None:
    if yes:
        return

    targets = [
        str(path)
        for path in _cleanup_targets(
            repo_root, output_dir, include_config=include_config
        )
    ]
    target_text = ", ".join(targets) if targets else str(output_dir)
    if not click.confirm(
        f"This will permanently delete DeepDoc output/state in {target_text}. Continue?",
        default=False,
    ):
        raise click.Abort()


def _wipe_deepdoc_output(
    repo_root: Path,
    output_dir: Path,
    include_config: bool = False,
) -> None:
    for path in _cleanup_targets(repo_root, output_dir, include_config=include_config):
        if path.is_dir():
            shutil.rmtree(path)
            continue
        path.unlink()


def _add_gitignore_entries(repo_root: Path, entries: list[str]) -> None:
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8")
    else:
        existing = ""
    new_entries = [e for e in entries if e not in existing]
    if new_entries:
        with open(gitignore, "a") as f:
            f.write("\n# DeepDoc\n")
            for e in new_entries:
                f.write(f"{e}\n")


def _deployment_quality_blockers(repo_root: Path, output_dir: Path) -> list[str]:
    blockers: list[str] = []

    quality_path = repo_root / ".deepdoc" / "generation_quality.json"
    if quality_path.exists():
        try:
            payload = json.loads(quality_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        pages_failed = int(payload.get("pages_failed", 0) or 0)
        pages_invalid = int(payload.get("pages_invalid", 0) or 0)
        if pages_failed:
            blockers.append(f"generation has {pages_failed} failed page(s)")
        if pages_invalid:
            blockers.append(f"generation has {pages_invalid} invalid page(s)")

    if output_dir.exists():
        invalid_pages: list[str] = []
        stub_pages: list[str] = []
        for doc_path in sorted(output_dir.glob("*.mdx")):
            try:
                content = doc_path.read_text(encoding="utf-8")
            except Exception:
                continue
            if 'deepdoc_status: "invalid"' in content:
                invalid_pages.append(doc_path.stem)
            if "stub: true" in content:
                stub_pages.append(doc_path.stem)
        if invalid_pages:
            blockers.append(
                "invalid docs present: " + ", ".join(invalid_pages[:8])
            )
        if stub_pages:
            blockers.append("stub docs present: " + ", ".join(stub_pages[:8]))

    return blockers


def _start_chatbot_backend(
    repo_root: Path,
    cfg: dict,
    frontend_port: int,
) -> tuple[subprocess.Popen | None, str]:
    import threading

    from .chatbot.scaffold import scaffold_chatbot_backend
    from .chatbot.settings import (
        chatbot_backend_port,
        chatbot_should_start_local_backend,
        configured_chatbot_backend_base_url,
    )

    configured_url = configured_chatbot_backend_base_url(cfg)
    if configured_url and not chatbot_should_start_local_backend(cfg):
        console.print(
            f"[dim]Using configured chatbot backend at {configured_url}[/dim]"
        )
        return None, configured_url

    scaffold_chatbot_backend(repo_root, cfg)

    backend_dir = repo_root / "chatbot_backend"
    if not (backend_dir / "app.py").exists():
        console.print(
            "[yellow]⚠ Chatbot backend scaffold missing; continuing without chat.[/yellow]"
        )
        return None, configured_url

    preferred_port = chatbot_backend_port(cfg, repo_root)
    port = _find_available_loopback_port(preferred_port)
    if port != preferred_port:
        console.print(
            f"[yellow]⚠ Chatbot backend port {preferred_port} is busy; using {port} instead.[/yellow]"
        )

    backend_url = f"http://127.0.0.1:{port}"
    console.print(f"[dim]Starting chatbot backend on http://127.0.0.1:{port}[/dim]")
    backend_env = os.environ.copy()
    backend_env["DEEPDOC_CHATBOT_PREVIEW_PORT"] = str(frontend_port)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "chatbot_backend.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(repo_root),
        env=backend_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    def _stream_stderr(process: subprocess.Popen) -> None:
        """Continuously read stderr and print to console."""
        try:
            for line in iter(process.stderr.readline, ""):
                if line.strip():
                    console.print(f"[dim][chatbot] {line.rstrip()}[/dim]")
                if process.poll() is not None:
                    break
        except (ValueError, OSError):
            pass
        if process.poll() is not None and process.returncode != 0:
            console.print("[yellow]⚠ Chatbot backend exited unexpectedly.[/yellow]")

    stderr_thread = threading.Thread(target=_stream_stderr, args=(proc,), daemon=True)
    stderr_thread.start()

    time.sleep(2)
    if proc.poll() is not None:
        console.print(
            "[yellow]⚠ Chatbot backend failed to start; docs will still serve.[/yellow]"
        )
        return None, configured_url
    return proc, backend_url


def _find_available_loopback_port(preferred_port: int) -> int:
    for candidate in range(preferred_port, preferred_port + 20):
        if _is_loopback_port_available(candidate):
            return candidate

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_loopback_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _flatten_config(cfg: dict, prefix: str, table) -> None:
    for k, v in cfg.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            _flatten_config(v, key, table)
        elif isinstance(v, list):
            table.add_row(key, ", ".join(str(i) for i in v) or "[dim](empty)[/dim]")
        else:
            table.add_row(key, str(v) if v is not None else "[dim]null[/dim]")


def _set_nested(d: dict, keys: list[str], value: str) -> None:
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    last = keys[-1]
    # Type coercion
    existing = d.get(last)
    if isinstance(existing, bool):
        d[last] = value.lower() in ("true", "1", "yes")
    elif isinstance(existing, int):
        d[last] = int(value)
    elif isinstance(existing, list):
        d[last] = [v.strip() for v in value.split(",")]
    else:
        d[last] = value


if __name__ == "__main__":
    main()
