# 📸 Stock Image & Vector Auto-Renamer

An automated AI-powered renaming tool designed specifically for stock photography and vector contributors (Adobe Stock, Shutterstock, Freepik, Getty). It scans your local folders, creates lightweight in-memory compressed previews to save slow network bandwidth (reducing 20MB+ files down to ~30KB), batches requests to Google Gemini Free Tier API, and renames files with commercial, SEO-optimized stock titles.

---

## ✨ Features

- **🚀 99%+ Bandwidth Savings**: Downscales high-resolution images/vectors to custom preview thumbnails (e.g. 640px @ 75% JPEG quality) directly in RAM.
- **🎨 Vector & Preview Pair Synchronization**: Automatically pairs `.eps` vector files with companion `.jpg`/`.png` files (e.g. `artwork.eps` + `artwork.jpg`) and renames both in perfect sync.
- **🤖 Free-Tier Optimized Batching**: Bundles 5–10 image previews per Gemini API request with structured JSON parsing to avoid rate limits (15 RPM free quota).
- **🛡️ 100% Safe Operations**:
  - **Dry-Run Mode (Default)**: Visual table preview of proposed names before touching any disk files.
  - **Collision Avoidance**: Automatic deduplication suffixes (`-1`, `-2`) if similar images share titles.
  - **One-Command Undo**: Instantly revert any rename batch at any time (`--undo`).
- **🎛️ Fully Customizable**: Choose casing styles (`kebab-case`, `snake_case`, `Title Case`), word limits, and custom prompt guidelines.

---

## 🛠️ Installation & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Get a Free Google Gemini API Key
1. Visit [Google AI Studio](https://aistudio.google.com/app/apikey) and create a free API key.
2. Create a `.env` file in the project folder (or copy `.env.example`):
```env
GEMINI_API_KEY=your_actual_api_key_here
```
*(Alternatively, you can pass `--api-key your_key` via CLI or set it in your system environment variables).*

---

## 🚀 Usage Examples

### 1. Dry Run Preview (Safe Test)
Preview proposed AI titles in a formatted table without renaming any files:
```bash
python rename.py "C:/path/to/my_stock_folder" --dry-run
```

### 2. Standard Interactive Rename
Scans the folder, analyzes via Gemini, displays the proposed names, and asks for your confirmation `[Y/n]` before applying:
```bash
python rename.py "C:/path/to/my_stock_folder"
```

### 3. Automatic Apply (Non-Interactive)
Rename immediately without confirmation prompt:
```bash
python rename.py "C:/path/to/my_stock_folder" -y
```

### 4. Low Bandwidth / Slow Connection Tuning
Further reduce thumbnail resolution to 480px and JPEG quality to 65% for ultra-fast uploads:
```bash
python rename.py "C:/path/to/my_stock_folder" --resolution 480 --quality 65 --batch-size 8
```

### 5. Custom Stock Prompt
Add specific guidelines (e.g. emphasize 3D isometric or watercolor style):
```bash
python rename.py "C:/path/to/my_stock_folder" --prompt "Focus on 3D isometric tech concepts and cyberpunk lighting."
```

### 6. Different Naming Styles
```bash
# Kebab-case (default for web SEO): african-safari-sunset-vector.jpg
python rename.py "C:/path/to/my_stock_folder" --style kebab

# Snake_case: african_safari_sunset_vector.jpg
python rename.py "C:/path/to/my_stock_folder" --style snake

# Title Case: African Safari Sunset Vector.jpg
python rename.py "C:/path/to/my_stock_folder" --style title
```

### 7. Instant Undo (Revert Changes)
If you want to revert the last batch rename and restore all original file names:
```bash
python rename.py "C:/path/to/my_stock_folder" --undo
```

---

## 📋 CLI Reference Options

| Flag | Short | Default | Description |
|---|---|---|---|
| `directory` | | `.` (Current) | Path to folder containing images/vectors |
| `--dry-run` | `-d` | `False` | Display proposed renames in table without touching disk |
| `--apply` | `-y` | `False` | Apply renames without interactive `[Y/n]` confirmation |
| `--batch-size` | `-b` | `6` | Number of image previews per Gemini API request |
| `--resolution` | `-r` | `640` | Max dimension in pixels for compressed preview |
| `--quality` | `-q` | `75` | JPEG preview compression quality (1-100) |
| `--style` | `-s` | `kebab` | Filename casing: `kebab`, `snake`, `title` |
| `--words` | | `8` | Maximum keywords/words in generated title |
| `--model` | | `gemini-3.6-flash` | Gemini model name |
| `--prompt` | | `None` | Custom prompt guidelines appended to system prompt |
| `--api-key` | | `None` | Override Gemini API Key |
| `--undo` | | `False` | Revert the last batch rename in the target directory |
| `--recursive`| | `False` | Recursively scan subfolders |

---

## 📁 Project Structure

```
.
├── rename.py                  # Main CLI launcher
├── run.bat                    # Windows batch launcher helper
├── requirements.txt           # Python dependencies
├── .env.example               # API Key template
├── stock_renamer/
│   ├── __init__.py
│   ├── config.py              # Configuration & prompt settings
│   ├── image_processor.py     # Image scanner, EPS pairer & thumbnail compressor
│   ├── gemini_client.py       # Batch Gemini API client & rate limiter
│   ├── renamer.py             # Sanitization, collision handler & undo engine
│   └── cli.py                 # Rich terminal UI & interactive workflow
└── tests/
    └── test_renamer.py        # Automated test suite
```
