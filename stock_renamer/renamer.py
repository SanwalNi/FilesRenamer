"""Safe file renamer with formatting, collision avoidance, and reversible undo history."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from .config import RenamerConfig
from .image_processor import StockAsset


class StockRenamer:
    """Handles filename normalization, conflict resolution, disk renames, and undo history."""

    def __init__(self, config: RenamerConfig):
        self.config = config

    def format_title_to_filename(self, title: str) -> str:
        """Converts raw title string into sanitized, style-formatted filename stem."""
        if not title:
            return "untitled"

        # Remove quotes, brackets, and invalid filesystem characters: < > : " / \ | ? *
        clean = re.sub(r'[<>:"/\\|?*\'"()\[\]{}]', '', title)
        # Replace multiple spaces, underscores, or hyphens with a single space
        clean = re.sub(r'[\s\-_]+', ' ', clean).strip()

        # Limit to max words
        words = clean.split()[: self.config.max_words]
        if not words:
            return "stock-asset"

        style = self.config.naming_style.lower()
        if style == "kebab":
            result = "-".join(w.lower() for w in words)
        elif style == "snake":
            result = "_".join(w.lower() for w in words)
        elif style == "title":
            result = " ".join(w.capitalize() for w in words)
        else:
            result = "-".join(w.lower() for w in words)

        # Enforce max character length
        max_chars = getattr(self.config, "max_chars", 180)
        if len(result) > max_chars:
            result = result[:max_chars].rstrip("-_ ")

        return result

    def prepare_renames(self, assets: List[StockAsset], target_dir: Path) -> List[StockAsset]:
        """
        Calculates unique, collision-free new paths for all files in all assets.
        Preserves pairing between EPS and JPG/PNG companion files.
        """
        used_stems: Set[str] = set()

        # Pre-populate used stems with existing files that are not part of this rename batch
        batch_paths = {f.resolve() for a in assets for f in a.paired_files}
        for existing_file in target_dir.iterdir():
            if existing_file.is_file() and existing_file.resolve() not in batch_paths:
                used_stems.add(existing_file.stem.lower())

        for asset in assets:
            if not asset.generated_title:
                continue

            base_stem = self.format_title_to_filename(asset.generated_title)
            candidate_stem = base_stem
            counter = 1

            # Resolve collisions
            sep = "_" if self.config.naming_style == "snake" else "-"
            while candidate_stem.lower() in used_stems:
                candidate_stem = f"{base_stem}{sep}{counter}"
                counter += 1

            used_stems.add(candidate_stem.lower())

            # Assign new filenames for all paired files
            asset.new_filenames = {}
            for original_file in asset.paired_files:
                new_name = f"{candidate_stem}{original_file.suffix}"
                new_path = original_file.parent / new_name
                asset.new_filenames[original_file] = new_path

        return assets

    def execute_renames(self, assets: List[StockAsset], target_dir: Path) -> Dict[str, Any]:
        """
        Executes actual filesystem renames and logs history for undo operations.
        """
        operations: List[Dict[str, str]] = []
        renamed_count = 0
        errors: List[str] = []

        for asset in assets:
            for old_path, new_path in asset.new_filenames.items():
                if old_path == new_path:
                    continue

                try:
                    if not old_path.exists():
                        errors.append(f"Source file not found: {old_path.name}")
                        continue

                    if new_path.exists() and old_path.resolve() != new_path.resolve():
                        errors.append(f"Target already exists, skipping: {new_path.name}")
                        continue

                    # Perform rename
                    old_path.rename(new_path)
                    operations.append({
                        "original_path": str(old_path.resolve()),
                        "new_path": str(new_path.resolve()),
                        "original_name": old_path.name,
                        "new_name": new_path.name
                    })
                    renamed_count += 1
                except Exception as e:
                    errors.append(f"Failed to rename '{old_path.name}' -> '{new_path.name}': {str(e)}")

        # Save history log for undo capability
        if operations:
            self._save_history_log(target_dir, operations)

        return {
            "renamed_count": renamed_count,
            "operations": operations,
            "errors": errors
        }

    def undo_last_operation(self, target_dir: Path) -> Dict[str, Any]:
        """
        Restores files to their original names from the latest history log entry.
        """
        history_path = target_dir / self.config.history_file
        if not history_path.exists():
            return {"success": False, "message": f"No rename history found at '{history_path}'."}

        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history_data = json.load(f)

            if not history_data or "batches" not in history_data or not history_data["batches"]:
                return {"success": False, "message": "History file contains no past rename batches."}

            last_batch = history_data["batches"].pop()
            reverted = 0
            errors = []

            for op in last_batch["operations"]:
                new_p = Path(op["new_path"])
                orig_p = Path(op["original_path"])

                try:
                    if new_p.exists():
                        new_p.rename(orig_p)
                        reverted += 1
                    else:
                        errors.append(f"File '{new_p.name}' not found to restore.")
                except Exception as e:
                    errors.append(f"Could not restore '{new_p.name}': {str(e)}")

            # Update history file
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history_data, f, indent=2)

            return {
                "success": True,
                "reverted_count": reverted,
                "batch_timestamp": last_batch.get("timestamp", "unknown"),
                "errors": errors
            }

        except Exception as e:
            return {"success": False, "message": f"Failed to undo: {str(e)}"}

    def _save_history_log(self, target_dir: Path, operations: List[Dict[str, str]]):
        """Appends current rename batch to the target directory's history log."""
        history_path = target_dir / self.config.history_file
        history_data: Dict[str, Any] = {"batches": []}

        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict) and "batches" in loaded:
                        history_data = loaded
            except Exception:
                pass

        history_data["batches"].append({
            "timestamp": datetime.now().isoformat(),
            "operations_count": len(operations),
            "operations": operations
        })

        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history_data, f, indent=2)
        except Exception as e:
            print(f"[Warning] Could not write rename history log: {e}")
