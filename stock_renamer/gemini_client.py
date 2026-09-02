"""Google Gemini Vision API client supporting structured batch responses and rate-limiting retry."""

import json
import re
import time
import warnings
from typing import Any, Dict, List, Optional
from .config import RenamerConfig
from .image_processor import StockAsset

# Suppress benign AFC UserWarning from google-genai SDK
warnings.filterwarnings("ignore", category=UserWarning, module="google")



class GeminiRenamerClient:
    """Interacts with Google Gemini API to analyze batches of image previews and generate stock titles."""

    def __init__(self, config: RenamerConfig):
        self.config = config
        self._client = None
        self._sdk_type = None
        self._initialize_client()

    def _initialize_client(self):
        """Initializes Google GenAI client."""
        if not self.config.api_key:
            raise ValueError(
                "Gemini API Key is missing! Set it via GEMINI_API_KEY environment variable, .env file, or --api-key flag.\n"
                "Get a free API key at: https://aistudio.google.com/app/apikey"
            )

        # Priority 1: Modern google-genai SDK
        try:
            from google import genai
            self._client = genai.Client(api_key=self.config.api_key)
            self._sdk_type = "google-genai"
            return
        except ImportError:
            pass

        # Priority 2: google.generativeai SDK
        try:
            import google.generativeai as legacy_genai
            legacy_genai.configure(api_key=self.config.api_key)
            self._client = legacy_genai
            self._sdk_type = "google-generativeai"
            return
        except ImportError:
            pass

        raise ImportError(
            "Neither 'google-genai' nor 'google-generativeai' is installed. "
            "Please run: pip install google-genai"
        )

    def process_batch(self, batch_assets: List[StockAsset], max_retries: int = 4) -> List[Dict[str, Any]]:
        """
        Sends a batch of compressed preview images to Gemini API and receives structured titles.
        Returns a list of result dictionaries with 'image_index', 'title', and 'keywords'.
        """
        if not batch_assets:
            return []

        # Filter only assets that generated previews successfully
        valid_assets = [a for a in batch_assets if a.thumbnail_bytes is not None]
        if not valid_assets:
            return []

        contents = self._prepare_batch_contents(valid_assets)

        for attempt in range(max_retries):
            try:
                raw_response = self._call_gemini_api(contents)
                parsed_results = self._parse_response(raw_response, len(valid_assets))
                return parsed_results

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str
                is_network_err = "timeout" in err_str or "connection" in err_str or "503" in err_str or "unavailable" in err_str or "high demand" in err_str

                if (is_rate_limit or is_network_err) and attempt < max_retries - 1:
                    wait_seconds = (attempt + 1) * 4
                    print(f"\n[Notice] Google API is busy/rate-limited (503/429). Retrying in {wait_seconds}s (attempt {attempt+1}/{max_retries})...")
                    time.sleep(wait_seconds)
                else:
                    raise RuntimeError(f"Gemini API request failed on attempt {attempt + 1}: {str(e)}")

        return []

    def _prepare_batch_contents(self, assets: List[StockAsset]) -> List[Any]:
        """Constructs prompt parts containing numbered image indicators and image bytes."""
        parts = []

        system_instruction = (
            f"{self.config.custom_prompt}\n\n"
            f"You are given {len(assets)} stock asset preview images numbered [Image 1] through [Image {len(assets)}].\n"
            f"Generate a descriptive title for EACH image (up to {self.config.max_words} words, up to {self.config.max_chars} characters).\n"
            "Respond ONLY with a valid JSON object matching the schema: "
            '{"results": [{"index": 1, "title": "...", "keywords": ["..."]}]}'
        )
        parts.append(system_instruction)

        for idx, asset in enumerate(assets, 1):
            parts.append(f"\n--- [Image {idx}] (Original: '{asset.primary_file.name}') ---")
            
            if self._sdk_type == "google-genai":
                from google.genai import types
                image_part = types.Part.from_bytes(
                    data=asset.thumbnail_bytes,
                    mime_type="image/jpeg"
                )
                parts.append(image_part)
            else:
                image_part = {
                    "mime_type": "image/jpeg",
                    "data": asset.thumbnail_bytes
                }
                parts.append(image_part)

        return parts

    def _call_gemini_api(self, contents: List[Any]) -> str:
        """Invokes the appropriate SDK method."""
        if self._sdk_type == "google-genai":
            from google.genai import types
            response = self._client.models.generate_content(
                model=self.config.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.4,
                ),
            )
            return response.text or ""
        else:
            model = self._client.GenerativeModel(
                model_name=self.config.model_name,
                generation_config={"response_mime_type": "application/json", "temperature": 0.4}
            )
            response = model.generate_content(contents)
            return response.text or ""

    def _parse_response(self, response_text: str, expected_count: int) -> List[Dict[str, Any]]:
        """Parses structured JSON response and validates image index mapping."""
        clean_text = response_text.strip()
        # Remove potential markdown code fences if present
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```(?:json)?\n?", "", clean_text)
            clean_text = re.sub(r"\n?```$", "", clean_text)
            clean_text = clean_text.strip()

        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError as e:
            # Fallback regex extraction of JSON object
            match = re.search(r"\{.*\}", clean_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                raise ValueError(f"Could not parse Gemini JSON response: {response_text[:200]}...") from e

        results = []
        if isinstance(data, dict):
            if "results" in data and isinstance(data["results"], list):
                results = data["results"]
            elif "items" in data and isinstance(data["items"], list):
                results = data["items"]
            else:
                # Check if it's a dict mapping indices e.g. {"1": {...}}
                for k, v in data.items():
                    if isinstance(v, dict):
                        results.append(v)
        elif isinstance(data, list):
            results = data

        return results
