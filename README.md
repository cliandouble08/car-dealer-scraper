# Multi-Website Dealer Scraper

A generalized, intelligent web scraper designed to extract dealership information (name, address, phone, website, etc.) from dealer locator websites. It uses AI (Jina Reader + Local LLM) to automatically analyze and adapt to different website structures without manual configuration.

## Features

-   **Multi-Website Support**: Scrape multiple dealer locator websites in one run.
-   **AI-Powered Analysis**: Uses **Jina Reader** to fetch content and a local **LLM (via Ollama)** to analyze page structure and determine CSS selectors automatically.
-   **Parallel Scraping**: Supports multi-process execution for faster results.
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

4.  **Setup Ollama (For AI Features)**:
    -   Install Ollama from [ollama.ai](https://ollama.ai).
    -   Pull a model (e.g., `llama3`):
        ```bash
        ollama pull llama3
        ```
    -   Start the Ollama server:
        ```bash
        ollama serve
        ```
    *See `LLM_FEATURES.md` for detailed AI setup instructions.*

## Usage

### 1. Prepare Inputs

**Websites File (`websites.txt`):**
Create a text file with one dealer locator URL per line.
```text
https://www.ford.com/dealerships/
https://www.toyota.com/dealers/
```

**Zip Codes:**
You can provide zip codes directly or use a file.
-   Use `generate_centroid_zips.py` to create an optimized list for nationwide coverage (see below).

### 2. Run the Scraper

The main script is `scrape_dealers.py`.

**Basic Run (Single Thread):**
```bash
python scrape_dealers.py --websites websites.txt --zip-codes "10001,90210" --no-headless
```

**Production Run (Parallel, Headless):**
```bash
python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt --headless --workers 4
```

**Command Arguments:**
-   `--websites`: Path to file containing website URLs (Required).
-   `--zip-codes`: Comma-separated list of zip codes (e.g., "10001,10002").
-   `--zip-file`: Path to a file containing zip codes (one per line).
-   `--output-dir`: Directory to save results (default: `output`).
-   `--headless`: Run browser in background (default). Use `--no-headless` to see the browser.
-   `--workers`: Number of parallel processes (default: 1).
-   `--enable-ai`: Enable AI features (default).
-   `--disable-ai`: Disable AI features and use default/manual selectors.

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

The scraper tries to figure out how to scrape a site automatically.
1.  **Check Cache**: Looks for existing config in `configs/llm_generated/` or `configs/`.
2.  **Jina & LLM**: If no config exists, it uses Jina Reader to read the site and Ollama to generate selectors.
3.  **Fallback**: If AI fails or is disabled, it falls back to `configs/base_config.yaml`.

For advanced details on how the AI analysis works, refer to `LLM_FEATURES.md`.

## Project Structure

-   `scrape_dealers.py`: Main scraping script.
-   `config_manager.py`: Manages loading and caching of scraping configurations.
-   `utils/`:
    -   `jina_reader.py`: Interface for Jina Reader API.
    -   `llm_analyzer.py`: Interface for Ollama LLM analysis.
    -   `extraction.py`: Parsers for addresses, phones, etc.
-   `configs/`: Stores generated and manual configuration files.
-   `data/`: Data storage.
-   `output/`: Scraped data results.
