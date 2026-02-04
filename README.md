# Multi-Website Dealer Scraper

A generalized, intelligent web scraper designed to extract dealership information (name, address, phone, website, etc.) from dealer locator websites. It uses AI (Crawl4AI + Jina Reader + Local LLM) to automatically discover, analyze, and adapt to different website structures without manual configuration.

## Features

-   **Multi-Website Support**: Scrape multiple dealer locator websites in one run.
-   **Intelligent URL Discovery**: Uses **Crawl4AI** to crawl websites and automatically find dealer locator pages.
-   **AI-Powered Analysis**: Uses **Jina Reader** to fetch content and a local **LLM (via Ollama)** to analyze page structure and determine CSS selectors automatically.
-   **Parallel Scraping**: Supports multi-process execution with both website-level and zip-code-level parallelism.
-   **Smart Popup Handling**: Automatically detects and handles blocking modals/popups that require zip code input.
-   **Smart Caching**: Caches LLM-generated configurations to avoid repeated analysis.
-   **Robust Automation**: Built on **Playwright** for reliable browser automation with fallback strategies (headless/visible, auto-retry, deduplication).
-   **Nationwide Coverage**: Includes tools to generate optimized zip code lists for full country coverage.

## Prerequisites

-   **Python 3.8+**
-   **Ollama** (Optional, for AI/LLM features)
-   **Chrome/Chromium** (Managed by Playwright)

## Installation

1.  **Clone the repository** (if applicable) and navigate to the directory.

2.  **Install Python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Install Playwright browsers**:
    ```bash
    playwright install chromium
    ```

4.  **Setup Crawl4AI** (for URL discovery):
    ```bash
    crawl4ai-setup
    ```

5.  **Setup Ollama (For AI Features)**:
    -   Install Ollama from [ollama.ai](https://ollama.ai).
    -   Pull a model (e.g., `gemma2:2b` - fast and efficient):
        ```bash
        ollama pull gemma2:2b
        ```
    -   Start the Ollama server:
        ```bash
        ollama serve
        ```

## Usage

### 1. Prepare Inputs

**Websites File (`websites.txt`):**
Create a text file with one dealer locator URL per line.
```text
https://www.ford.com/dealerships/
https://www.toyota.com/dealers/
```

**Zip Codes:**
You can provide zip codes directly via `--zip-codes` or use a file via `--zip-file`.

**Option 1: Inline zip codes**
```bash
python scrape_dealers.py --websites websites.txt --zip-codes "10001,90210,60601"
```

**Option 2: Zip codes from a .txt file**
Create a text file with one zip code per line:
```text
# Comments start with #
10001
90210
60601
# 00000  # Commented out zip codes are skipped
```

Then use the `--zip-file` flag:
```bash
python scrape_dealers.py --websites websites.txt --zip-file my_zip_codes.txt
```

You can also combine both flags - zip codes from both sources will be merged:
```bash
python scrape_dealers.py --websites websites.txt --zip-codes "10001" --zip-file additional_zips.txt
```

**Tip:** Use `generate_centroid_zips.py` to create an optimized list for nationwide coverage (see below).

### 2. Run the Scraper

The main script is `scrape_dealers.py`.

**Basic Run (Single Thread):**
```bash
python scrape_dealers.py --websites websites.txt --zip-codes "10001,90210" --no-headless
```

**Parallel Zip Codes (per website):**
```bash
python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt --workers 4
```

**Parallel Websites + Parallel Zip Codes:**
```bash
python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt --website-workers 2 --workers 4
```

**Command Arguments:**
-   `--websites`: Path to file containing website URLs (Required).
-   `--zip-codes`: Comma-separated list of zip codes (e.g., "10001,10002").
-   `--zip-file`: Path to a file containing zip codes (one per line).
-   `--output-dir`: Directory to save results (default: `output`).
-   `--headless`: Run browser in background (default). Use `--no-headless` to see the browser.
-   `--workers`, `-w`: Number of parallel workers for zip codes per website (default: 1).
-   `--website-workers`: Number of websites to scrape in parallel (default: 1, max: 4).
-   `--enable-ai`: Enable AI features (default).
-   `--disable-ai`: Disable AI features and use default/manual selectors.
-   `--list-websites`: List websites from the file and exit.

### 3. Output

Results are saved in the `output/` directory in both CSV and JSON formats:
-   `{domain}_dealers_{timestamp}.csv`
-   `{domain}_dealers_{timestamp}.json`

## Helper Scripts

### `generate_centroid_zips.py`
Generates a list of zip codes that ensures 100% geographic coverage of the US based on a specified radius.

```bash
# Generate zip codes for 50-mile search radius
python generate_centroid_zips.py --radius 50 --output centroid_zip_codes.txt
```

### `find_dealer_locators.py`
Helps find the dealer locator URL for specific brands.

```bash
# Edit the script to add brands, then run:
python find_dealer_locators.py
```

## AI & Configuration

The scraper uses a multi-stage approach to automatically configure itself:

1.  **Check Cache**: Looks for existing config in `configs/llm_generated/` or `configs/`.
2.  **URL Discovery (Crawl4AI)**: If starting from a generic URL (e.g., homepage), uses Crawl4AI to extract all links and LLM to identify the dealer locator page.
3.  **Page Analysis (Jina + LLM)**: Fetches content via Jina Reader and uses Ollama to analyze page structure, identifying CSS selectors for inputs, buttons, and dealer cards.
4.  **Popup Detection**: Analyzes if the page has blocking modals/popups that require zip code input before showing results.
5.  **Fallback**: If AI fails or is disabled, falls back to `configs/base_config.yaml`.

### Popup/Modal Handling

The scraper automatically handles blocking popups (like Toyota's location prompt):
1.  First tries pressing **Escape** to dismiss the popup.
2.  If Escape doesn't work, finds the zip input within the popup and submits it.
3.  Waits for the overlay to dismiss before proceeding with the main page.

### Using a Different LLM Model

The default model is `gemma2:2b` (fast, ~1.5GB). You can use any Ollama-compatible model:

**Option 1: Set environment variable before running**
```bash
export LLM_MODEL="llama3"
python scrape_dealers.py --websites websites.txt --zip-codes "10001"
```

**Option 2: Inline for a single run**
```bash
LLM_MODEL="llama3" python scrape_dealers.py --websites websites.txt --zip-codes "10001"
```

**Recommended Models:**

| Model | Size | Speed | Quality | Use Case |
|-------|------|-------|---------|----------|
| `gemma2:2b` | ~1.5GB | Fast | Good | Default, quick analysis |
| `llama3` | ~4.7GB | Medium | Better | More accurate selectors |
| `llama3:70b` | ~40GB | Slow | Best | Complex sites (requires GPU) |
| `mistral` | ~4.1GB | Medium | Good | Alternative to llama3 |
| `codellama` | ~3.8GB | Medium | Good | Code-focused analysis |

**Install a new model:**
```bash
ollama pull llama3        # Download llama3
ollama pull mistral       # Download mistral
ollama list               # See installed models
```

**Using a remote Ollama instance:**
```bash
export LLM_ENDPOINT="http://remote-server:11434/api/generate"
export LLM_MODEL="llama3"
python scrape_dealers.py --websites websites.txt --zip-codes "10001"
```

## Environment Variables

```bash
export LLM_ENDPOINT="http://localhost:11434/api/generate"  # Ollama endpoint
export LLM_MODEL="gemma2:2b"                               # Model name (default)
export LLM_TIMEOUT="120"                                   # Timeout in seconds
export LLM_MAX_TOKENS="1500"                               # Max response tokens
export JINA_READER_ENABLED="true"                          # Enable/disable Jina Reader
export LLM_ANALYSIS_ENABLED="true"                         # Enable/disable LLM analysis
export JINA_SSL_VERIFY="true"                              # SSL verification (set to "false" for corporate proxies)
export JINA_CA_BUNDLE="/path/to/ca-bundle.crt"             # Custom CA bundle path
export SCRAPER_DEBUG="false"                               # Enable debug logging
```

## Project Structure

-   `scrape_dealers.py`: Main scraping script with parallel execution support.
-   `config_manager.py`: Manages loading and caching of scraping configurations.
-   `utils/`:
    -   `crawl4ai_discovery.py`: URL discovery using Crawl4AI for finding dealer locator pages.
    -   `jina_reader.py`: Interface for Jina Reader API with rate limiting and retry logic.
    -   `llm_analyzer.py`: Interface for Ollama LLM analysis with popup detection.
    -   `dynamic_config.py`: Generates configs from LLM analysis results.
    -   `extraction.py`: Parsers for addresses, phones, distances, etc.
-   `configs/`: Stores generated and manual configuration files.
    -   `base_config.yaml`: Default selectors and patterns including popup handling.
    -   `llm_generated/`: Auto-generated configs from AI analysis.
-   `data/`: Data storage including analysis artifacts.
-   `output/`: Scraped data results.

## Troubleshooting

### Playwright Not Installed
```bash
pip install playwright
playwright install chromium
```

### Crawl4AI Setup Failed
```bash
pip install crawl4ai
crawl4ai-setup
```

### LLM Connection Error
```bash
# Make sure Ollama is running
ollama serve

# Verify the model is installed
ollama list
```

### No Dealers Found
1.  Run with `--no-headless` to see the browser.
2.  Check `data/analysis/{domain}/` for screenshots and content.
3.  Verify the LLM-generated config in `configs/llm_generated/`.
4.  Create a manual override in `configs/{domain}.yaml`.

### Rate Limiting (429 Errors)
The scraper automatically handles rate limiting with exponential backoff. If you're seeing persistent 429 errors:
-   Reduce the number of parallel workers.
-   Increase delays in the config (`wait_after_search`, etc.).

### SSL Certificate Errors
For corporate proxies or SSL interception:
```bash
export JINA_SSL_VERIFY="false"
# Or point to your CA bundle:
export JINA_CA_BUNDLE="/path/to/ca-bundle.crt"
```
