import argparse
import sys
from pathlib import Path
from typing import List

# Ensure UTF-8 encoding on Windows consoles to prevent UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from .config import RenamerConfig, DEFAULT_STOCK_PROMPT
from .image_processor import ImageProcessor, StockAsset
from .gemini_client import GeminiRenamerClient
from .renamer import StockRenamer


console = Console(highlight=False)


def format_bytes(size: int) -> str:
    """Formats raw byte count into human-readable MB / KB."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def print_banner():
    """Prints tool header banner."""
    console.print(
        Panel.fit(
            "[bold cyan]📸 Stock Image & Vector Auto-Renamer[/bold cyan]\n"
            "[dim]Powered by Google Gemini Vision API • Bandwidth-Optimized • Batch-Processed[/dim]",
            border_style="cyan",
        )
    )


def run_undo(target_dir: Path, config: RenamerConfig):
    """Executes undo command to revert previous rename operations."""
    renamer = StockRenamer(config)
    console.print(f"[bold yellow]↺ Undoing last batch rename in:[/bold yellow] [dim]{target_dir}[/dim]")
    result = renamer.undo_last_operation(target_dir)

    if result.get("success"):
        console.print(
            f"[bold green]✓ Successfully restored {result['reverted_count']} files![/bold green] "
            f"[dim](Batch from {result.get('batch_timestamp')})[/dim]"
        )
        if result.get("errors"):
            for err in result["errors"]:
                console.print(f"[red]! {err}[/red]")
    else:
        console.print(f"[bold red]✗ Undo failed:[/bold red] {result.get('message')}")


def main():
    parser = argparse.ArgumentParser(
        description="Auto-rename stock photos, vectors (EPS), and illustrations using Google Gemini AI."
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Path to folder containing stock images/vectors (default: current folder)",
    )
    parser.add_argument(
        "-d", "--dry-run",
        action="store_true",
        help="Preview proposed renames in table without touching disk files",
    )
    parser.add_argument(
        "-y", "--apply",
        action="store_true",
        help="Apply renames directly to disk without interactive confirmation",
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=6,
        help="Number of image previews sent per Gemini API request (default: 6)",
    )
    parser.add_argument(
        "-r", "--resolution",
        type=int,
        default=640,
        help="Max preview dimension in pixels (default: 640px, saves bandwidth)",
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=75,
        help="JPEG preview compression quality 1-100 (default: 75)",
    )
    parser.add_argument(
        "-s", "--style",
        choices=["title", "kebab", "snake"],
        default=None,
        help="Filename casing style: 'title' (Foo Bar.jpg), 'kebab' (foo-bar.jpg), 'snake' (foo_bar.jpg)",
    )
    parser.add_argument(
        "--words",
        type=int,
        default=None,
        help="Max keywords/words in generated filename (default: 25)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="Max character length for filenames (default: 180)",
    )
    parser.add_argument(
        "--model",
        default="gemini-3.6-flash",
        help="Gemini model to use (default: gemini-3.6-flash)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Custom additional instructions for Gemini naming (or edit prompt.txt)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Google Gemini API Key (or set GEMINI_API_KEY environment variable)",
    )
    parser.add_argument(
        "--undo",
        action="store_true",
        help="Revert the last batch rename performed in the target directory",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively scan subfolders",
    )

    args = parser.parse_args()

    print_banner()

    target_dir = Path(args.directory).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        console.print(f"[bold red]Error:[/bold red] Target path '{target_dir}' does not exist or is not a directory.")
        sys.exit(1)

    # Initialize configuration
    config = RenamerConfig(
        preview_max_dimension=args.resolution,
        jpeg_quality=args.quality,
        batch_size=args.batch_size,
        model_name=args.model,
        recursive=args.recursive,
    )

    if args.style:
        config.naming_style = args.style
    if args.words:
        config.max_words = args.words
    if args.max_chars:
        config.max_chars = args.max_chars

    if args.api_key:
        config.api_key = args.api_key

    if args.prompt:
        config.custom_prompt = f"{DEFAULT_STOCK_PROMPT}\nAdditional User Guidelines:\n{args.prompt}"

    # Handle Undo
    if args.undo:
        run_undo(target_dir, config)
        sys.exit(0)

    # Step 1: Scan Directory
    console.print(f"\n[cyan]🔍 Scanning directory:[/cyan] [dim]{target_dir}[/dim]")
    processor = ImageProcessor(config)
    assets = processor.scan_directory(target_dir)

    if not assets:
        console.print("[yellow]No supported image or vector files (.jpg, .jpeg, .png, .webp, .eps, .ai, .svg) found.[/yellow]")
        sys.exit(0)

    total_files_count = sum(len(a.paired_files) for a in assets)
    total_raw_bytes = sum(a.original_size_bytes for a in assets)
    console.print(f"[green]✓ Found {len(assets)} unique assets[/green] ({total_files_count} total files including vector/preview pairs).")

    # Step 2: Generate compressed in-memory previews
    console.print(f"[cyan]⚡ Generating lightweight compressed previews ({config.preview_max_dimension}px @ {config.jpeg_quality}% quality)...[/cyan]")
    valid_assets: List[StockAsset] = []
    total_preview_bytes = 0

    with console.status("[bold green]Compressing previews in memory...") as status:
        for asset in assets:
            if processor.generate_preview(asset):
                valid_assets.append(asset)
                total_preview_bytes += asset.preview_size_bytes
            else:
                console.print(f"[yellow]⚠ Skipped '{asset.primary_file.name}': {asset.error_message}[/yellow]")

    if not valid_assets:
        console.print("[bold red]No valid image previews could be generated.[/bold red]")
        sys.exit(1)

    # Bandwidth savings summary
    savings_pct = (1.0 - (total_preview_bytes / max(total_raw_bytes, 1))) * 100
    console.print(
        f"[bold green]✓ Previews Ready:[/bold green] Compressed from [bold]{format_bytes(total_raw_bytes)}[/bold] "
        f"down to [bold cyan]{format_bytes(total_preview_bytes)}[/bold cyan] "
        f"([bold yellow]{savings_pct:.1f}% bandwidth saved[/bold yellow])\n"
    )

    # Step 3: Call Gemini API in Batches
    console.print(f"[cyan]🤖 Sending batches to Gemini API ([bold]{config.model_name}[/bold])...[/cyan]")
    try:
        gemini_client = GeminiRenamerClient(config)
    except Exception as e:
        console.print(f"[bold red]Configuration Error:[/bold red] {e}")
        sys.exit(1)

    batch_size = config.batch_size
    total_batches = (len(valid_assets) + batch_size - 1) // batch_size

    for b_idx in range(0, len(valid_assets), batch_size):
        batch = valid_assets[b_idx : b_idx + batch_size]
        batch_num = (b_idx // batch_size) + 1
        console.print(f"  [dim]• Batch {batch_num}/{total_batches} ({len(batch)} items)...[/dim]", end="\r")

        try:
            results = gemini_client.process_batch(batch)
            for idx, res in enumerate(results):
                title = res.get("title") or res.get("name") or res.get("suggested_name")
                img_idx = res.get("image_index") or res.get("index") or (idx + 1)
                
                # Match by index (1-based)
                if isinstance(img_idx, int) and 1 <= img_idx <= len(batch):
                    batch[img_idx - 1].generated_title = title
                elif idx < len(batch):
                    batch[idx].generated_title = title

            # Fallback for any missing items in batch
            for idx, a in enumerate(batch):
                if not a.generated_title and idx < len(results):
                    a.generated_title = results[idx].get("title") or f"stock-asset-{idx+1}"

        except Exception as e:
            console.print(f"\n[red]✗ Error processing batch {batch_num}: {e}[/red]")

    console.print(f"\n[bold green]✓ Analysis complete for all {len(valid_assets)} assets![/bold green]\n")

    # Step 4: Prepare Renames & Collision Handling
    renamer = StockRenamer(config)
    renamer.prepare_renames(valid_assets, target_dir)

    # Display Preview Table
    table = Table(title="Proposed Stock Renames", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Original Files", style="cyan")
    table.add_column("AI Suggested Title", style="yellow")
    table.add_column("New Filename(s)", style="green")

    for i, asset in enumerate(valid_assets, 1):
        orig_names = ", ".join(f.name for f in asset.paired_files)
        new_names = ", ".join(f.name for f in asset.new_filenames.values()) if asset.new_filenames else "[red]Failed[/red]"
        title = asset.generated_title or "[dim]N/A[/dim]"
        table.add_row(str(i), orig_names, title, new_names)

    console.print(table)

    # Step 5: Execute Renames or Dry Run
    if args.dry_run:
        console.print("\n[bold yellow]ℹ DRY RUN MODE: No files were changed on disk.[/bold yellow]")
        console.print("To apply these changes, run without [bold cyan]--dry-run[/bold cyan] or use [bold cyan]-y[/bold cyan].")
        sys.exit(0)

    should_apply = args.apply
    if not should_apply:
        should_apply = Confirm.ask("\n[bold cyan]Apply these renames to disk now?[/bold cyan]", default=True)

    if should_apply:
        console.print("\n[cyan]Writing changes to disk...[/cyan]")
        result = renamer.execute_renames(valid_assets, target_dir)
        console.print(f"[bold green]✓ Successfully renamed {result['renamed_count']} files![/bold green]")
        console.print(f"[dim]Saved undo history to: {target_dir / config.history_file}[/dim]")
        if result["errors"]:
            for err in result["errors"]:
                console.print(f"[red]! {err}[/red]")
    else:
        console.print("[yellow]Operation cancelled. No files were modified.[/yellow]")

    # Keep window open when launched via Windows shortcut
    if not args.apply:
        try:
            console.print("\n[dim]Press Enter to close...[/dim]")
            input()
        except Exception:
            pass


if __name__ == "__main__":
    main()
