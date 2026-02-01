# LLM-Powered Adaptive Scraper Features

## Overview

The scraper now includes intelligent LLM-based analysis that automatically understands new manufacturer websites and extracts the necessary selectors and interaction patterns. This makes the scraper truly generalizable without manual configuration.

## How It Works

1. **First Visit Detection**: When scraping a new manufacturer for the first time, the system checks if an LLM-generated config exists.

2. **Jina Reader Integration**: If no config exists, the system uses [Jina Reader](https://r.jina.ai/) to fetch LLM-friendly content from the manufacturer's website.

3. **LLM Analysis**: The content is sent to a local LLM (Ollama) which analyzes the page structure and extracts:
   - CSS selectors for search inputs, dealer cards, buttons, etc.
   - Interaction patterns (delays, timeouts)
   - Extraction patterns (regex for names, phones, addresses)

4. **Config Generation**: The LLM output is converted to a YAML config file and cached.

5. **Automatic Usage**: The generated config is automatically used for all subsequent scraping runs.

## Setup

### 1. Install Ollama

The LLM analysis uses Ollama (local LLM). Install it from: https://ollama.ai/

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model (recommended: llama3 or mistral)
ollama pull llama3
# or
ollama pull mistral
```

### 2. Start Ollama Server

```bash
ollama serve
```

The server runs on `http://localhost:11434` by default.

### 3. Environment Variables (Optional)

You can configure the LLM settings via environment variables:

```bash
export LLM_ENDPOINT="http://localhost:11434/api/generate"  # Default
export LLM_MODEL="llama3"  # Default
export LLM_TIMEOUT="120"  # Seconds, default: 120
export JINA_READER_ENABLED="true"  # Enable/disable Jina Reader
export LLM_ANALYSIS_ENABLED="true"  # Enable/disable LLM analysis
```

## Usage

The LLM analysis happens automatically on first visit to a new manufacturer website. No additional commands needed!

```bash
# First run - will trigger LLM analysis for Ford
python scrape_dealers.py --brand ford --zip-file test_zip_codes.txt

# Subsequent runs - uses cached LLM config
python scrape_dealers.py --brand ford --zip-file test_zip_codes.txt
```

## Cache Location

LLM-generated configs are cached in:
- **File cache**: `configs/llm_generated/{brand}_llm.yaml`
- **Memory cache**: In-memory during current session

## Config Priority

The scraper uses configs in this priority order (highest to lowest):
1. Manual config (`configs/{brand}.yaml`) - if exists
2. LLM-generated config (`configs/llm_generated/{brand}_llm.yaml`) - if exists
3. Base config (`configs/base_config.yaml`)
4. Auto-detection fallback

## Disabling LLM Features

If you want to disable LLM analysis:

```bash
export LLM_ANALYSIS_ENABLED="false"
```

Or disable Jina Reader:

```bash
export JINA_READER_ENABLED="false"
```

## Troubleshooting

### LLM Connection Error

If you see: `Error: Cannot connect to LLM at http://localhost:11434`

- Make sure Ollama is running: `ollama serve`
- Check if the endpoint is correct: `export LLM_ENDPOINT="http://localhost:11434/api/generate"`

### Jina Reader Timeout

If Jina Reader fails to fetch content:
- The scraper will fall back to auto-detection
- Check your internet connection
- Some sites may block automated access

### Low Confidence Results

If LLM analysis has low confidence (< 0.5):
- The config is still saved but may need manual refinement
- Check the generated config in `configs/llm_generated/`
- You can manually edit it or create a manual override in `configs/{brand}.yaml`

## Manual Override

If you want to override LLM-generated configs, create a manual config file:

```bash
# Create configs/toyota.yaml
# This will override any LLM-generated config for Toyota
```

## Example LLM-Generated Config

```yaml
manufacturer: Toyota
base_url: https://www.toyota.com/dealers/
generated_by: llm_analyzer
generated_date: 2026-01-30T12:00:00
confidence: 0.85
notes: "Found clear dealer card structure with consistent selectors"
selectors:
  search_input:
    - "input[placeholder*='Zip']"
    - "input[name='zipcode']"
  dealer_cards:
    - "div[class*='dealer-card']"
    - "li[data-dealer-id]"
  apply_button:
    - "button[type='submit']"
  view_more_button:
    - "button:contains('Load More')"
interactions:
  wait_after_search: 4
  scroll_delay: 0.5
extraction:
  name_patterns:
    - "^(.+?)\\s*\\|"
  phone_patterns:
    - "\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}"
```

## Benefits

1. **Zero Configuration**: Works with new manufacturers automatically
2. **Intelligent Caching**: Avoids redundant LLM calls
3. **Graceful Fallbacks**: Multiple layers ensure scraping continues even if LLM fails
4. **Privacy**: Uses local LLM, no data sent to external services
5. **Cost-Effective**: No API costs for LLM analysis
