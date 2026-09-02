"""Automated unit and integration tests for Stock Image & Vector Auto-Renamer."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from stock_renamer.config import RenamerConfig
from stock_renamer.image_processor import ImageProcessor, StockAsset
from stock_renamer.renamer import StockRenamer


class TestStockRenamer(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_stock_renamer_"))
        self.config = RenamerConfig(
            preview_max_dimension=400,
            jpeg_quality=70,
            batch_size=4,
            naming_style="kebab",
            max_words=6,
        )
        self.processor = ImageProcessor(self.config)
        self.renamer = StockRenamer(self.config)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_dummy_image(self, filename: str, size=(1200, 800), color="blue") -> Path:
        """Helper to create test dummy image."""
        p = self.test_dir / filename
        img = Image.new("RGB", size, color=color)
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), f"Test {filename}", fill="white")
        img.save(p)
        return p

    def _create_dummy_eps(self, filename: str) -> Path:
        """Helper to create dummy EPS file with PS text."""
        p = self.test_dir / filename
        with open(p, "w", encoding="utf-8") as f:
            f.write("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 100\n%%Title: Test EPS\nshowpage\n")
        return p

    def test_scan_and_pairing(self):
        """Test scanning directory and grouping paired EPS + JPG files."""
        # Create single JPEG
        self._create_dummy_image("photo_single.jpg")
        # Create single PNG
        self._create_dummy_image("photo_single2.png")
        # Create paired vector + preview
        self._create_dummy_eps("vector_artwork.eps")
        self._create_dummy_image("vector_artwork.jpg")

        assets = self.processor.scan_directory(self.test_dir)
        self.assertEqual(len(assets), 3)

        # Verify paired asset
        paired_asset = next((a for a in assets if a.original_stem == "vector_artwork"), None)
        self.assertIsNotNone(paired_asset)
        self.assertEqual(len(paired_asset.paired_files), 2)
        suffixes = {f.suffix.lower() for f in paired_asset.paired_files}
        self.assertEqual(suffixes, {".eps", ".jpg"})
        # Primary file should be the raster preview
        self.assertEqual(paired_asset.primary_file.suffix.lower(), ".jpg")

    def test_preview_generation_and_compression(self):
        """Test downscaling in memory and bandwidth reduction."""
        img_path = self._create_dummy_image("large_photo.jpg", size=(2000, 1500))
        asset = StockAsset(primary_file=img_path)

        success = self.processor.generate_preview(asset)
        self.assertTrue(success)
        self.assertEqual(asset.status, "ready")
        self.assertIsNotNone(asset.thumbnail_bytes)

        # Verify thumbnail dimensions
        thumb_img = Image.open(io_bytes := io_from_bytes(asset.thumbnail_bytes))
        self.assertLessEqual(max(thumb_img.size), self.config.preview_max_dimension)
        # Verify preview size is tiny (e.g. < 50KB for compressed JPEG)
        self.assertLess(asset.preview_size_bytes, 50 * 1024)

    def test_title_formatting(self):
        """Test kebab, snake, and title casing normalization."""
        raw_title = "Modern Businesswoman Working On Laptop (Office Setting) / HD*!"

        self.config.naming_style = "kebab"
        self.assertEqual(
            self.renamer.format_title_to_filename(raw_title),
            "modern-businesswoman-working-on-laptop-office"
        )

        self.config.naming_style = "snake"
        self.assertEqual(
            self.renamer.format_title_to_filename(raw_title),
            "modern_businesswoman_working_on_laptop_office"
        )

        self.config.naming_style = "title"
        self.assertEqual(
            self.renamer.format_title_to_filename(raw_title),
            "Modern Businesswoman Working On Laptop Office"
        )

    def test_long_descriptive_title_formatting(self):
        """Test long 150-character descriptive titles are preserved when max_words is large."""
        long_title = "Autumn Red Maple Leaf Vector Illustration Isolated on White Background with Vibrant Orange and Brown Colors for Thanksgiving Design"
        self.config.max_words = 25
        self.config.max_chars = 180
        self.config.naming_style = "title"

        formatted = self.renamer.format_title_to_filename(long_title)
        self.assertEqual(formatted, "Autumn Red Maple Leaf Vector Illustration Isolated On White Background With Vibrant Orange And Brown Colors For Thanksgiving Design")
        self.assertTrue(len(formatted) > 100)
        self.assertLessEqual(len(formatted), 180)


    def test_collision_resolution_and_paired_renaming(self):
        """Test handling duplicate generated titles and synchronizing paired files."""
        self._create_dummy_eps("a_vector_01.eps")
        self._create_dummy_image("a_vector_01.jpg")
        self._create_dummy_image("b_photo_02.jpg")

        assets = self.processor.scan_directory(self.test_dir)

        # Simulate Gemini returning the same title for two distinct assets
        for a in assets:
            a.generated_title = "golden-autumn-forest-trees"

        self.renamer.prepare_renames(assets, self.test_dir)

        # Verify first asset gets base name and paired files share identical stem
        paired_asset = next(a for a in assets if a.original_stem == "a_vector_01")
        new_names = [p.name for p in paired_asset.new_filenames.values()]
        self.assertIn("golden-autumn-forest-trees.eps", new_names)
        self.assertIn("golden-autumn-forest-trees.jpg", new_names)

        # Verify collision was resolved with suffix for the second asset
        other_asset = next(a for a in assets if a.original_stem == "b_photo_02")
        other_new_name = list(other_asset.new_filenames.values())[0].name
        self.assertEqual(other_new_name, "golden-autumn-forest-trees-1.jpg")

    def test_execute_rename_and_undo(self):
        """Test executing disk renames and completely reverting them with undo."""
        f1 = self._create_dummy_image("IMG_0001.jpg")
        f2 = self._create_dummy_image("IMG_0002.jpg")

        assets = self.processor.scan_directory(self.test_dir)
        assets[0].generated_title = "tropical-beach-ocean-wave"
        assets[1].generated_title = "mountain-peak-sunset-view"

        self.renamer.prepare_renames(assets, self.test_dir)
        exec_result = self.renamer.execute_renames(assets, self.test_dir)

        self.assertEqual(exec_result["renamed_count"], 2)
        self.assertFalse(f1.exists())
        self.assertFalse(f2.exists())
        self.assertTrue((self.test_dir / "tropical-beach-ocean-wave.jpg").exists())
        self.assertTrue((self.test_dir / "mountain-peak-sunset-view.jpg").exists())

        # Test Undo
        undo_result = self.renamer.undo_last_operation(self.test_dir)
        self.assertTrue(undo_result["success"])
        self.assertEqual(undo_result["reverted_count"], 2)

        # Verify original files are back
        self.assertTrue(f1.exists())
        self.assertTrue(f2.exists())
        self.assertFalse((self.test_dir / "tropical-beach-ocean-wave.jpg").exists())
        self.assertFalse((self.test_dir / "mountain-peak-sunset-view.jpg").exists())


def io_from_bytes(b: bytes):
    import io
    return io.BytesIO(b)


if __name__ == "__main__":
    unittest.main()
