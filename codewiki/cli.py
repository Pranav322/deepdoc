"""CodeWiki CLI — codewiki init | generate | update | serve | deploy"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import DEFAULT_CONFIG, CONFIG_FILE, find_config, load_config, save_config

console = Console()
CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 100,
}


# ─────────────────────────────────────────────────────────────────────────────
# CLI group
# ─────────────────────────────────────────────────────────────────────────────

@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(__version__, prog_name="codewiki")
@click.pass_context
def main(ctx: click.Context) -> None:
    """
    Generate, update, preview, and deploy documentation for a repository.

    \b
    Typical workflow:
      1. codewiki init
      2. codewiki generate
      3. codewiki serve
      4. codewiki update

    Use `codewiki <command> --help` for examples and next-step guidance.
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─────────────────────────────────────────────────────────────────────────────
# init
# ─────────────────────────────────────────────────────────────────────────────

@main.command(short_help="Create .codewiki.yaml for the current repository.")
@click.option("--name", default="", show_default=False,
              help="Project name shown in the generated docs. Defaults to the current directory name.")
@click.option("--description", default="", show_default=False,
              help="Short project description used in config and site metadata.")
@click.option("--provider", default="anthropic", show_default=True,
              type=click.Choice(["anthropic", "openai", "ollama", "azure"], case_sensitive=False),
              help="LLM provider to configure for the first run.")
@click.option("--model", default="", show_default=False,
              help="Model name to store in config. If omitted, CodeWiki picks a provider-specific default.")
@click.option("--output-dir", default="docs", show_default=True,
              help="Directory where generated Markdown docs will be written.")
@click.option("--with-chatbot", is_flag=True,
              help="Enable code-and-artifact chatbot scaffolding and indexing in generated repos.")
def init(name, description, provider, model, output_dir, with_chatbot):
    """Initialize CodeWiki in the current repository.

    This command creates `.codewiki.yaml` and fills in sensible defaults for the chosen provider.

    \b
    Examples:
      codewiki init
      codewiki init --provider openai --model gpt-4o
      codewiki init --provider ollama --model ollama/llama3.2
      codewiki init --output-dir documentation
    """
    cwd = Path.cwd()

    if (cwd / CONFIG_FILE).exists():
        console.print(f"[yellow]⚠ {CONFIG_FILE} already exists. Overwrite?[/yellow] (y/N) ", end="")
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
            ".codewiki/chatbot/",
            "chatbot_backend/.venv/",
            "chatbot_backend/__pycache__/",
            ".codewiki_manifest.json",
        ],
    )

    next_steps = [
        f"  1. Review config:     [bold]codewiki config show[/bold]",
    ]
    if cfg["llm"]["api_key_env"]:
        next_steps.append(
            f"  2. Set your API key:  [bold]export {cfg['llm']['api_key_env']}=...[/bold]"
        )
        next_steps.append("  3. Generate docs:     [bold]codewiki generate[/bold]")
        next_steps.append("  4. Preview locally:   [bold]codewiki serve[/bold]")
    else:
        next_steps.append("  2. Make sure Ollama is running locally")
        next_steps.append("  3. Generate docs:     [bold]codewiki generate[/bold]")
        next_steps.append("  4. Preview locally:   [bold]codewiki serve[/bold]")
    if with_chatbot:
        next_steps.append(
            "  5. Set chatbot keys:  [bold]export CODEWIKI_CHAT_API_KEY=... CODEWIKI_EMBED_API_KEY=...[/bold]"
        )

    console.print(Panel.fit(
        f"[bold green]✓ CodeWiki initialized![/bold green]\n\n"
        f"Config saved to [cyan]{CONFIG_FILE}[/cyan]\n"
        f"Docs will be generated to [cyan]{output_dir}/[/cyan]\n\n"
        f"[dim]Next steps:[/dim]\n" + "\n".join(next_steps),
        title="CodeWiki",
        border_style="green",
    ))


# ─────────────────────────────────────────────────────────────────────────────
# generate
# ─────────────────────────────────────────────────────────────────────────────

@main.command(short_help="Create docs for the current repository.")
@click.option("--force", is_flag=True,
              help="Fully refresh existing CodeWiki-managed docs instead of refusing to overwrite them.")
@click.option("--clean", is_flag=True,
              help="Delete generated docs and saved CodeWiki state, then rebuild from scratch.")
@click.option("--yes", is_flag=True,
              help="Skip the confirmation prompt used by destructive actions such as --clean.")
@click.option("--include", multiple=True,
              help="Restrict scanning to these glob patterns. Repeat the flag to include multiple roots.")
@click.option("--exclude", multiple=True,
              help="Add extra glob patterns to exclude for this run. Repeat the flag as needed.")
@click.option("--deploy", is_flag=True,
              help="Run `codewiki deploy` automatically after a successful generation.")
@click.option("--batch-size", default=10, show_default=True,
              help="How many pages to generate per batch before pausing briefly for rate limits.")
def generate(force, clean, yes, include, exclude, deploy, batch_size):
    """Generate documentation for the entire codebase.

    \b
    When to use which mode:
      codewiki generate              First run in a repo
      codewiki generate --force      Full refresh of existing CodeWiki docs
      codewiki generate --clean      Wipe docs + saved state, then rebuild

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
        _wipe_codewiki_output(repo_root, output_dir)
        output_state = _inspect_output_state(repo_root, output_dir)

    if output_state["codewiki_managed"] and not effective_force:
        raise click.ClickException(
            f"CodeWiki docs already exist in {output_dir}. "
            "Use `codewiki update` for incremental refresh, "
            "`codewiki generate --force` for a full refresh, "
            "or `codewiki generate --clean --yes` to rebuild from scratch."
        )

    if output_state["has_files"] and not output_state["codewiki_managed"] and not clean:
        raise click.ClickException(
            f"{output_dir} already exists and does not look CodeWiki-managed. "
            "Use a different output directory or run `codewiki generate --clean --yes` "
            "to replace it explicitly."
        )

    if include:
        cfg["include"] = list(include)
    if exclude:
        cfg["exclude"] = cfg.get("exclude", []) + list(exclude)
    cfg["batch_size"] = batch_size

    console.print(Panel.fit(
        f"[bold]Generating docs for [cyan]{cfg.get('project_name') or repo_root.name}[/cyan][/bold]\n"
        f"Provider: [dim]{cfg['llm']['provider']}[/dim]  Model: [dim]{cfg['llm']['model']}[/dim]",
        border_style="blue",
    ))

    from .pipeline_v2 import PipelineV2
    pipeline = PipelineV2(repo_root, cfg)
    pipeline.run(force=effective_force, reconcile=force and not clean)

    if deploy:
        ctx = click.get_current_context()
        ctx.invoke(_deploy)


# ─────────────────────────────────────────────────────────────────────────────
# update
# ─────────────────────────────────────────────────────────────────────────────

@main.command(short_help="Refresh docs after source code changes.")
@click.option("--since", default=None,
              help="Git ref to diff against (e.g. HEAD~3, main). "
                   "Defaults to the last synced commit, or HEAD~1 if none.")
@click.option("--deploy", is_flag=True,
              help="Run `codewiki deploy` automatically after a successful update.")
@click.option("--replan", is_flag=True,
              help="Force a full replan even if CodeWiki thinks an incremental update would be enough.")
def update(since, deploy, replan):
    """Incrementally update docs for files changed since last sync.

    Run `codewiki generate` once before using this command.

    \b
    Smart update strategy:
      incremental   Regenerate only buckets affected by changed files
      targeted      Replan when new integrations or structures appear
      full replan   Used for large structural changes or when --replan is set

    The strategy is chosen automatically based on what changed.
    If no --since is provided, CodeWiki diffs from the commit where docs
    were last fully synced (stored in .codewiki/state.json).
    """
    cfg = _load_or_exit()
    repo_root = _find_repo_root()

    # Resolve --since: explicit override > saved baseline > HEAD~1 fallback
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
            since = "HEAD~1"
            console.print(
                "[dim]No sync baseline found — using HEAD~1. "
                "Run [bold]codewiki generate[/bold] to establish a baseline.[/dim]"
            )

    mode = cfg.get("generation_mode", "feature_buckets")
    if mode == "feature_buckets":
        from .smart_update_v2 import SmartUpdater
        updater = SmartUpdater(repo_root, cfg)
        stats = updater.update(since=since, force_replan=replan)
        count = stats.get("pages_updated", 0)
    else:
        console.print(Panel.fit(
            f"[bold]Updating docs[/bold] since [cyan]{since}[/cyan]",
            border_style="blue",
        ))
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

@main.command(short_help="Show what CodeWiki has generated and what is stale.")
def status():
    """Show documentation generation status and stale buckets.

    \b
    Use this after `generate` or `update` to see how many pages were produced and
    whether any buckets now look out of date.
    """
    from rich.table import Table
    cfg = _load_or_exit()
    repo_root = _find_repo_root()

    from .persistence_v2 import load_plan, ledger_summary, find_stale_buckets, load_generation_ledger
    plan = load_plan(repo_root)
    if plan is None or not hasattr(plan, "buckets"):
        console.print("[yellow]No v2 bucket plan found. Run [bold]codewiki generate[/bold] first.[/yellow]")
        return

    summary = ledger_summary(repo_root)
    console.print(Panel.fit(
        f"[bold]Documentation Status[/bold]\n\n"
        f"  Buckets planned:   [cyan]{len(plan.buckets)}[/cyan]\n"
        f"  Pages generated:   [cyan]{summary.get('successful', 0)}[/cyan]\n"
        f"  Pages failed:      [cyan]{summary.get('failed', 0)}[/cyan]\n"
        f"  Total words:       [cyan]{summary.get('total_words', 0):,}[/cyan]\n"
        f"  Total diagrams:    [cyan]{summary.get('total_diagrams', 0)}[/cyan]\n"
        f"  By type:           [cyan]{summary.get('by_bucket_type', {})}[/cyan]",
        border_style="blue",
    ))

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
        console.print("\n[dim]Run [bold]codewiki update[/bold] to refresh stale pages.[/dim]")
    else:
        console.print("[green]✓ All pages are up-to-date.[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# serve
# ─────────────────────────────────────────────────────────────────────────────

@main.command(short_help="Serve the generated docs locally with live reload.")
@click.option("--port", default=3000, show_default=True,
              help="Port to bind the local Fumadocs development server to.")
def serve(port):
    """Preview the generated docs locally with live reload.

    \b
    Run `codewiki generate` first so the generated Fumadocs app and docs exist.
    Requires Node.js >= 18 to be installed.
    """
    _load_or_exit()
    cfg = _load_or_exit()
    repo_root = _find_repo_root()
    site_dir = repo_root / "site"

    package_json = site_dir / "package.json"
    if not package_json.exists():
        console.print("[red]site/package.json not found. Run [bold]codewiki generate[/bold] first.[/red]")
        sys.exit(1)

    preview_url = f"http://localhost:{port}"
    console.print(f"[bold]Serving docs at [link={preview_url}]{preview_url}[/link][/bold]")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")

    try:
        backend_proc = None
        if cfg.get("chatbot", {}).get("enabled"):
            backend_proc = _start_chatbot_backend(repo_root, cfg)
        if not (site_dir / "node_modules").exists():
            console.print("[dim]Installing site dependencies...[/dim]")
            install = subprocess.run(["npm", "install"], cwd=str(site_dir), capture_output=False)
            if install.returncode != 0:
                console.print("[red]npm install failed.[/red]")
                sys.exit(1)

        subprocess.run(
            ["npx", "next", "dev", "--port", str(port)],
            cwd=str(site_dir),
        )
    except KeyboardInterrupt:
        pass
    except FileNotFoundError:
        console.print("[red]npm/npx not found. Install Node.js >= 18: https://nodejs.org[/red]")
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
      1. Run `codewiki deploy`
      2. Publish `site/out/` to any static host
    """
    _load_or_exit()
    repo_root = _find_repo_root()
    site_dir = repo_root / "site"

    package_json = site_dir / "package.json"
    if not package_json.exists():
        console.print("[red]site/package.json not found. Run [bold]codewiki generate[/bold] first.[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        "[bold]Fumadocs Deployment:[/bold]\n\n"
        "1. [bold cyan]Static export:[/bold cyan]\n"
        "   Run: [bold]codewiki deploy[/bold]\n"
        "   Publish [bold]site/out/[/bold] to any static host\n\n"
        "2. [bold cyan]Suggested hosts:[/bold cyan]\n"
        "   Vercel, Netlify, GitHub Pages, Cloudflare Pages, or any CDN/static server",
        title="Deploy",
        border_style="green",
    ))
    cfg = _load_or_exit()
    if cfg.get("chatbot", {}).get("enabled"):
        console.print(
            "[yellow]Chatbot mode is enabled.[/yellow] Deploy [bold]chatbot_backend/[/bold] "
            "separately on an internal Python host and point [bold]chatbot.backend.base_url[/bold] at it."
        )

    # Offer to run a static build
    console.print("\n[dim]Running static build...[/dim]")
    try:
        if not (site_dir / "node_modules").exists():
            console.print("[dim]Installing site dependencies...[/dim]")
            install = subprocess.run(["npm", "install"], cwd=str(site_dir), capture_output=False)
            if install.returncode != 0:
                console.print("[red]npm install failed.[/red]")
                sys.exit(1)

        build_result = subprocess.run(
            ["npx", "next", "build"],
            cwd=str(site_dir),
            capture_output=False,
        )
        if build_result.returncode == 0:
            console.print("[bold green]✓ Build complete! Static files are in site/out/[/bold green]")
        else:
            console.print("[red]Build failed.[/red]")
    except FileNotFoundError:
        console.print("[red]npm/npx not found. Install Node.js >= 18: https://nodejs.org[/red]")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# config show
# ─────────────────────────────────────────────────────────────────────────────

@main.group("config", context_settings=CONTEXT_SETTINGS, invoke_without_command=True, short_help="Show or edit `.codewiki.yaml` values.")
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """Inspect or update `.codewiki.yaml` without opening the file manually.

    \b
    Examples:
      codewiki config show
      codewiki config set llm.model claude-3-5-sonnet-20241022
      codewiki config set llm.provider openai
      codewiki config set output_dir documentation
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@config_cmd.command("show", short_help="Print the current merged config.")
def config_show() -> None:
    """Print the current CodeWiki config in a readable table."""
    cfg_path = find_config()
    if cfg_path is None:
        console.print("[red]No .codewiki.yaml found. Run [bold]codewiki init[/bold] first.[/red]")
        sys.exit(1)

    cfg = load_config(cfg_path)
    table = Table(title="CodeWiki Config", show_header=True, header_style="bold")
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
      codewiki config set llm.provider openai
      codewiki config set llm.model gpt-4o
      codewiki config set output_dir documentation
      codewiki config set exclude tests/**,dist/**,build/**
    """
    if not value:
        raise click.UsageError(
            "Please provide a value. Example: codewiki config set llm.model gpt-4o"
        )

    cfg_path = find_config()
    if cfg_path is None:
        console.print("[red]No .codewiki.yaml found. Run [bold]codewiki init[/bold] first.[/red]")
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
        console.print("[red]No .codewiki.yaml found. Run [bold]codewiki init[/bold] first.[/red]")
        sys.exit(1)
    return load_config(cfg_path)


def _find_repo_root() -> Path:
    """Find the directory containing .codewiki.yaml."""
    cfg_path = find_config()
    return cfg_path.parent if cfg_path else Path.cwd()


def _inspect_output_state(repo_root: Path, output_dir: Path) -> dict[str, bool]:
    has_files = output_dir.exists() and any(output_dir.iterdir())
    markers = [
        output_dir / ".codewiki_manifest.json",
        repo_root / ".codewiki" / "plan.json",
        repo_root / ".codewiki" / "ledger.json",
        repo_root / ".codewiki_plan.json",
        repo_root / ".codewiki_file_map.json",
    ]
    return {
        "has_files": has_files,
        "codewiki_managed": any(marker.exists() for marker in markers),
    }


def _confirm_clean(repo_root: Path, output_dir: Path, yes: bool) -> None:
    if yes:
        return

    targets = []
    if output_dir.exists():
        targets.append(str(output_dir))
    if (repo_root / ".codewiki").exists():
        targets.append(str(repo_root / ".codewiki"))
    if (repo_root / "site").exists():
        targets.append(str(repo_root / "site"))
    if (repo_root / "chatbot_backend").exists():
        targets.append(str(repo_root / "chatbot_backend"))

    target_text = ", ".join(targets) if targets else str(output_dir)
    if not click.confirm(
        f"This will permanently delete CodeWiki output/state in {target_text}. Continue?",
        default=False,
    ):
        raise click.Abort()


def _wipe_codewiki_output(repo_root: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)

    state_dir = repo_root / ".codewiki"
    if state_dir.exists():
        shutil.rmtree(state_dir)

    site_dir = repo_root / "site"
    if site_dir.exists():
        shutil.rmtree(site_dir)
    backend_dir = repo_root / "chatbot_backend"
    if backend_dir.exists():
        shutil.rmtree(backend_dir)

    for path in (
        repo_root / ".codewiki_plan.json",
        repo_root / ".codewiki_file_map.json",
    ):
        if path.exists():
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
            f.write("\n# CodeWiki\n")
            for e in new_entries:
                f.write(f"{e}\n")


def _start_chatbot_backend(repo_root: Path, cfg: dict) -> subprocess.Popen | None:
    import threading

    from .chatbot.scaffold import scaffold_chatbot_backend
    from .chatbot.settings import chatbot_backend_port

    scaffold_chatbot_backend(repo_root, cfg)

    backend_dir = repo_root / "chatbot_backend"
    if not (backend_dir / "app.py").exists():
        console.print("[yellow]⚠ Chatbot backend scaffold missing; continuing without chat.[/yellow]")
        return None

    port = chatbot_backend_port(cfg)
    console.print(f"[dim]Starting chatbot backend on http://127.0.0.1:{port}[/dim]")
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
        console.print("[yellow]⚠ Chatbot backend failed to start; docs will still serve.[/yellow]")
        return None
    return proc


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
