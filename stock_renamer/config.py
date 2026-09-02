"""Configuration management for Stock Image & Vector Auto-Renamer."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Automatically look for .env in current working directory and project root
load_dotenv()


def load_default_prompt() -> str:
    """Loads prompt from prompt.txt if it exists, otherwise uses hardcoded default."""
    candidates = [
        Path.cwd() / "prompt.txt",
        Path(__file__).parent.parent / "prompt.txt",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception:
                pass

    return """You are an expert Adobe Stock, Shutterstock, and Freepik contributor and commercial SEO specialist.
Analyze each image carefully. For each numbered image, generate a clean, literal, highly descriptive commercial stock title (aim for 100 to 150 characters).

Rules for stock titles:
1. Provide a detailed, literal descriptive title describing subject, visual attributes, actions, context, and style.
2. Focus on clear, high-search-volume commercial keywords describing the image content.
3. Avoid spam words or generic filler like "image", "photo_of", "stock", "beautiful", "amazing", "pic", "hd".
4. If it is a vector or pattern, include descriptors like "Vector Illustration", "Graphic Pattern", or "Background".
5. Keep names clean, natural, and readable without special symbols.
"""


DEFAULT_STOCK_PROMPT = load_default_prompt()


@dataclass
class RenamerConfig:
    """Settings and configuration for scanning, compression, API batching, and renaming."""

    # API Settings
    api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    )
    model_name: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # Preview & Network Optimization Settings
    preview_max_dimension: int = 640  # Max width/height in px for thumbnail (drastically reduces bandwidth)
    jpeg_quality: int = 75           # Compression quality (1-100) for preview JPEG
    batch_size: int = 6              # Number of images sent in a single Gemini API call (1-12)

    # Naming Settings
    naming_style: str = os.getenv("NAMING_STYLE", "title")  # 'title' (Foo Bar.png), 'kebab' (foo-bar.png), or 'snake' (foo_bar.png)
    max_words: int = int(os.getenv("MAX_WORDS", "25"))       # Maximum word count in generated titles
    max_chars: int = int(os.getenv("MAX_CHARS", "180"))       # Maximum character length for filenames
    custom_prompt: str = field(default_factory=load_default_prompt)

    # Supported Extensions
    raster_extensions: List[str] = field(
        default_factory=lambda: [".jpg", ".jpeg", ".png", ".webp"]
    )
    vector_extensions: List[str] = field(
        default_factory=lambda: [".eps", ".ai", ".svg"]
    )

    # Behavior Flags
    dry_run: bool = True             # Safe default: preview changes without renaming
    recursive: bool = False          # Scan subdirectories recursively
    auto_confirm: bool = False       # Skip interactive confirmation prompt
    history_file: str = "rename_history.json"

    def get_all_supported_extensions(self) -> List[str]:
        """Returns all recognized image and vector extensions (lowercased)."""
        return [ext.lower() for ext in self.raster_extensions + self.vector_extensions]
