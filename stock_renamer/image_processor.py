"""Image and vector scanner, paired-file matcher, and bandwidth-optimized thumbnail generator."""

import io
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from PIL import Image

from .config import RenamerConfig


@dataclass
class StockAsset:
    """Represents a stock asset (either a standalone image or a paired vector + preview)."""

    primary_file: Path
    paired_files: List[Path] = field(default_factory=list)
    original_stem: str = ""
    thumbnail_bytes: Optional[bytes] = None
    original_size_bytes: int = 0
    preview_size_bytes: int = 0
    status: str = "pending"
    error_message: Optional[str] = None
    generated_title: Optional[str] = None
    new_filenames: Dict[Path, Path] = field(default_factory=dict)

    def __post_init__(self):
        if not self.original_stem:
            self.original_stem = self.primary_file.stem
        if not self.paired_files:
            self.paired_files = [self.primary_file]
        self.calculate_original_size()

    def calculate_original_size(self):
        """Calculates combined file size on disk for all paired files."""
        total = 0
        for f in self.paired_files:
            try:
                if f.exists():
                    total += f.stat().st_size
            except Exception:
                pass
        self.original_size_bytes = total


class ImageProcessor:
    """Scans directories, groups vector/raster pairs, and generates ultra-low-bandwidth previews."""

    def __init__(self, config: RenamerConfig):
        self.config = config

    def scan_directory(self, target_dir: Path) -> List[StockAsset]:
        """
        Scans target_dir for supported image and vector files, grouping paired files with matching stems.
        Example: vector_01.eps + vector_01.jpg are grouped together.
        """
        if not target_dir.exists() or not target_dir.is_dir():
            raise FileNotFoundError(f"Target directory '{target_dir}' does not exist or is not a directory.")

        all_files: List[Path] = []
        pattern = "**/*" if self.config.recursive else "*"

        for file_path in target_dir.glob(pattern):
            if file_path.is_file() and not file_path.name.startswith("."):
                ext = file_path.suffix.lower()
                if ext in self.config.get_all_supported_extensions():
                    all_files.append(file_path)

        # Group by directory and base stem (to handle pairs within the same folder)
        # Key: (parent_dir_str, lower_stem)
        groups: Dict[Tuple[str, str], List[Path]] = {}
        for f in all_files:
            key = (str(f.parent.resolve()), f.stem.lower())
            groups.setdefault(key, []).append(f)

        assets: List[StockAsset] = []

        for (parent_str, stem), files in sorted(groups.items()):
            # Determine the primary file to use for visual thumbnail extraction
            # Priority: .jpg/.jpeg > .png > .webp > .eps > .svg > other
            raster_files = [f for f in files if f.suffix.lower() in self.config.raster_extensions]
            vector_files = [f for f in files if f.suffix.lower() in self.config.vector_extensions]

            if raster_files:
                # Prefer JPEG if available, else first raster
                jpgs = [f for f in raster_files if f.suffix.lower() in [".jpg", ".jpeg"]]
                primary = jpgs[0] if jpgs else raster_files[0]
            else:
                primary = vector_files[0]

            asset = StockAsset(
                primary_file=primary,
                paired_files=sorted(files, key=lambda x: x.suffix),
                original_stem=primary.stem,
            )
            assets.append(asset)

        return assets

    def generate_preview(self, asset: StockAsset) -> bool:
        """
        Generates a downscaled, compressed JPEG thumbnail in memory.
        Returns True if successful, False if failed.
        """
        try:
            image = self._load_image(asset.primary_file)
            if image is None:
                # If primary failed and there are other files in the pair, try alternatives
                for alt_file in asset.paired_files:
                    if alt_file != asset.primary_file:
                        image = self._load_image(alt_file)
                        if image:
                            break

            if image is None:
                asset.status = "error"
                asset.error_message = (
                    f"Could not render image preview for '{asset.primary_file.name}'."
                )
                return False

            # Convert to RGB (handling transparency with clean white background)
            rgb_image = self._convert_to_rgb(image)

            # Resize maintaining aspect ratio
            max_dim = self.config.preview_max_dimension
            rgb_image.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # Compress to memory buffer
            buf = io.BytesIO()
            rgb_image.save(
                buf,
                format="JPEG",
                quality=self.config.jpeg_quality,
                optimize=True,
            )
            preview_data = buf.getvalue()

            asset.thumbnail_bytes = preview_data
            asset.preview_size_bytes = len(preview_data)
            asset.status = "ready"
            return True

        except Exception as e:
            asset.status = "error"
            asset.error_message = f"Error processing '{asset.primary_file.name}': {str(e)}"
            return False

    def _load_image(self, file_path: Path) -> Optional[Image.Image]:
        """Loads an image from file path, including native EPS embedded header handling."""
        ext = file_path.suffix.lower()

        # Handle EPS files
        if ext == ".eps":
            # Attempt 1: Extract and decode embedded TIFF thumbnail (Adobe Illustrator/Photoshop header)
            tiff_img = self._extract_eps_embedded_thumbnail(file_path)
            if tiff_img:
                return tiff_img

            # Attempt 2: Extract embedded JPEG/PNG from PostScript comments
            ps_img = self._extract_eps_postscript_preview(file_path)
            if ps_img:
                return ps_img

            # Attempt 3: Standard PIL open (requires Ghostscript)
            try:
                img = Image.open(file_path)
                img.load()
                return img
            except Exception:
                return None

        # Standard Raster Files (JPG, PNG, WEBP, etc.)
        try:
            img = Image.open(file_path)
            img.load()
            return img
        except Exception:
            return None

    def _convert_to_rgb(self, img: Image.Image) -> Image.Image:
        """Converts transparent PNGs/RGBA/CMYK/Palette images to standard RGB with white background."""
        if img.mode == "RGB":
            return img.copy()

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            # Create a solid white background
            alpha_img = img.convert("RGBA")
            bg = Image.new("RGBA", alpha_img.size, (255, 255, 255, 255))
            composite = Image.alpha_composite(bg, alpha_img)
            return composite.convert("RGB")

        if img.mode == "CMYK":
            return img.convert("RGB")

        if img.mode == "P":
            return img.convert("RGB")

        return img.convert("RGB")

    def _extract_eps_embedded_thumbnail(self, eps_path: Path) -> Optional[Image.Image]:
        """
        Parses Adobe EPS binary header (0xC5D0D3C6) and decodes embedded TIFF thumbnail
        (including Illustrator 8-bit Indexed + Alpha palette format).
        """
        try:
            with open(eps_path, "rb") as f:
                header = f.read(30)
                if len(header) < 30:
                    return None

                # Check for standard EPS binary magic number 0xC5D0D3C6
                if header[:4] == b"\xc5\xd0\xd3\xc6":
                    _, ps_off, ps_len, wmf_off, wmf_len, tiff_off, tiff_len = struct.unpack(
                        "<IIIIIII", header[:28]
                    )

                    if tiff_off > 0 and tiff_len > 0:
                        f.seek(tiff_off)
                        tiff_data = f.read(tiff_len)
                        if tiff_data:
                            return self._decode_tiff_data(tiff_data)
        except Exception:
            pass
        return None

    def _decode_tiff_data(self, tiff_data: bytes) -> Optional[Image.Image]:
        """Decodes raw TIFF bytes supporting Illustrator palette/alpha format."""
        if len(tiff_data) < 8:
            return None

        endian_char = "<" if tiff_data[:2] == b"II" else ">" if tiff_data[:2] == b"MM" else None
        if not endian_char:
            return None

        try:
            ifd_offset = struct.unpack(f"{endian_char}I", tiff_data[4:8])[0]
            num_tags = struct.unpack(f"{endian_char}H", tiff_data[ifd_offset : ifd_offset + 2])[0]

            tags: Dict[int, Tuple[int, int, int]] = {}
            for i in range(num_tags):
                tag, typ, count, val_or_off = struct.unpack(
                    f"{endian_char}HHII",
                    tiff_data[ifd_offset + 2 + i * 12 : ifd_offset + 14 + i * 12],
                )
                tags[tag] = (typ, count, val_or_off)

            width = tags.get(0x100, (0, 0, 0))[2]
            height = tags.get(0x101, (0, 0, 0))[2]
            photometric = tags.get(0x106, (0, 0, 0))[2]
            samples_per_pixel = tags.get(0x115, (0, 0, 1))[2]
            strip_offset = tags.get(0x111, (0, 0, 0))[2]
            colormap_off = tags.get(0x140, (0, 0, 0))[2]

            # Adobe Illustrator Indexed Palette + Alpha TIFF (Photometric 3)
            if photometric == 3 and colormap_off and width and height and strip_offset:
                colormap_bytes = tiff_data[colormap_off : colormap_off + 768 * 2]
                colormap = struct.unpack(f"{endian_char}768H", colormap_bytes)
                r_map = [c >> 8 for c in colormap[0:256]]
                g_map = [c >> 8 for c in colormap[256:512]]
                b_map = [c >> 8 for c in colormap[512:768]]

                raw_pixels = tiff_data[strip_offset : strip_offset + width * height * samples_per_pixel]
                palette_indices = raw_pixels[0::samples_per_pixel]

                p_img = Image.frombytes("P", (width, height), palette_indices)
                flat_palette = []
                for i in range(256):
                    flat_palette.extend([r_map[i], g_map[i], b_map[i]])
                p_img.putpalette(flat_palette)
                return p_img.convert("RGB")

            # Standard RGB / RGBA TIFF
            if photometric == 2 and width and height and strip_offset:
                raw_pixels = tiff_data[strip_offset : strip_offset + width * height * samples_per_pixel]
                mode = "RGB" if samples_per_pixel == 3 else "RGBA"
                img = Image.frombytes(mode, (width, height), raw_pixels)
                return img.convert("RGB")

            # Fallback to PIL standard open
            return Image.open(io.BytesIO(tiff_data))

        except Exception:
            try:
                return Image.open(io.BytesIO(tiff_data))
            except Exception:
                return None

    def _extract_eps_postscript_preview(self, eps_path: Path) -> Optional[Image.Image]:
        """Scans PostScript comments for embedded JPEG or ASCII hex preview."""
        try:
            with open(eps_path, "rb") as f:
                content = f.read(100000)  # Read first 100KB header

            # Check for embedded JPEG binary marker
            jpg_start = content.find(b"\xff\xd8\xff")
            if jpg_start != -1:
                jpg_end = content.find(b"\xff\xd9", jpg_start)
                if jpg_end != -1:
                    jpg_data = content[jpg_start : jpg_end + 2]
                    return Image.open(io.BytesIO(jpg_data))

            # Check for EPSI/%%BeginPreview
            preview_match = re.search(rb"%%BeginPreview:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", content)
            if preview_match:
                w, h, depth, lines = map(int, preview_match.groups())
                start_pos = preview_match.end()
                end_pos = content.find(b"%%EndPreview", start_pos)
                if end_pos != -1:
                    hex_data = re.sub(rb"[\s%]", b"", content[start_pos:end_pos])
                    raw_bytes = bytes.fromhex(hex_data.decode("ascii", errors="ignore"))
                    if depth == 1:
                        return Image.frombytes("1", (w, h), raw_bytes).convert("RGB")
                    elif depth == 8:
                        return Image.frombytes("L", (w, h), raw_bytes).convert("RGB")
        except Exception:
            pass
        return None
