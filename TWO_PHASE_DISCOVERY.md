# Two-Phase LLM Discovery System

## Overview

The scraper now uses a **two-phase LLM discovery** approach:

1. **Phase 1 (Pre-Search)**: Discover form elements
2. **Phase 2 (Post-Search)**: Discover data field selectors

This ensures the scraper adapts to the actual search results page structure.

## Why Two Phases?

### Problem
Different websites structure their dealer information differently:
- Some use `<h2 class="dealer-name">`
- Others use `<div class="name">`
- Phone numbers might be in `<a href="tel:...">` or plain text
- Addresses could be single or multi-element

**Traditional approach**: Guess selectors or use static YAML configs
**New approach**: Let LLM analyze the actual search results

## Phase 1: Form Discovery (Before Search)

**When**: On initial page load (before entering zip code)

**What LLM finds**:
```json
{
  "zip_input": "input#dealer-search-zip",
  "submit_button": "button.search-dealers",
  "view_more_button": "button.load-more",
  "dealer_cards": "div.dealer-result-card"
}
```

**Example LLM prompt**:
```
Analyze this dealer locator page and identify:
1. ZIP CODE INPUT: The input field for zip/postal code
2. SUBMIT BUTTON: The button that submits the search
3. VIEW MORE BUTTON: Button to load additional results (optional)
4. DEALER CARDS: The container for each dealer result
```

## Phase 2: Data Field Discovery (After Search)

**When**: After zip code is entered and search results appear

**What LLM finds**:
```json
{
  "name": {
    "selector": "h2.dealer-name",
    "type": "text"
  },
  "address": {
    "selector": ".dealer-address",
    "type": "text"
  },
  "phone": {
    "selector": "a.phone-link",
    "type": "href",
    "attribute": "href"
  },
  "website": {
    "selector": "a.website-link",
    "type": "href",
    "attribute": "href"
  },
  "distance": {
    "selector": ".distance-miles",
    "type": "text"
  }
}
```

**Example LLM prompt**:
```
Analyze this dealer search results page.

For EACH dealer card/listing, identify:
1. DEALER NAME: The dealership name (h1, h2, .dealer-name, etc.)
2. ADDRESS: Street address, city, state, zip
3. PHONE NUMBER: Phone contact (<a href="tel:">, .phone, etc.)
4. WEBSITE: Dealer's website URL
5. DISTANCE: Distance from search location (optional)

Return CSS selectors RELATIVE to the dealer card.
```

## Complete Workflow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Navigate to Dealer Locator                              │
│    https://www.ford.com/dealerships/                        │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. PHASE 1 - LLM Discovery (Form Elements)                 │
│    - Analyze initial page                                   │
│    - Find: zip input, submit button, dealer cards selector │
│                                                              │
│    Result: {                                                │
│      zip_input: "input#zipCode",                            │
│      submit_button: "button.search-btn",                    │
│      dealer_cards: "li.dealer-card"                         │
│    }                                                         │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Fill Zip Code & Submit                                  │
│    input.value = "10001"                                    │
│    button.click()                                           │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Wait for Search Results                                 │
│    - Poll for dealer cards to appear                       │
│    - Max 30 seconds                                         │
│    - Found 25 dealer cards                                  │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. PHASE 2 - LLM Discovery (Data Fields)                   │
│    - Analyze search results page                           │
│    - Understand how dealer info is labeled/structured      │
│    - Find: name, address, phone, website selectors         │
│                                                              │
│    Result: {                                                │
│      name: {selector: "h2.dealer-name", type: "text"},      │
│      address: {selector: ".address", type: "text"},         │
│      phone: {selector: "a.tel", type: "href"},              │
│      website: {selector: "a.site", type: "href"}            │
│    }                                                         │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Expand Results                                           │
│    - Click "Load More" 30 times                             │
│    - OR scroll to load all dealers                          │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 7. Extract Using Discovered Selectors                      │
│    For each dealer card:                                    │
│      name = card.select("h2.dealer-name")                   │
│      address = card.select(".address")                      │
│      phone = card.select("a.tel")['href']                   │
│      website = card.select("a.site")['href']                │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 8. Save Results                                             │
│    CSV: ford_com_dealers_20260203.csv                       │
│    JSON: ford_com_dealers_20260203.json                     │
└─────────────────────────────────────────────────────────────┘
```

## Benefits

### ✅ Adaptive to Actual Results
- Analyzes the real search results, not the empty form
- Handles different layouts across websites
- Works even if site structure changes after deployment

### ✅ Better Accuracy
- Selectors are based on actual DOM structure
- LLM sees the populated page with real dealer data
- Can distinguish between similar elements (e.g., dealer phone vs support phone)

### ✅ Semantic Understanding
- LLM understands "this is a phone number" even if class name is generic
- Can identify address fields even without "address" in the class name
- Recognizes patterns like `href="tel:..."` for phone numbers

### ✅ No Manual Configuration
- Zero YAML configuration needed
- Works with any dealer locator website
- Self-configuring for each domain

## Browser Window Management

### Issue: `about:blank` After Scraping

**Problem**: In `--no-headless` mode, browser navigates to `about:blank` after scraping

**Why**: Session cleanup kills the page

**Solution**: Keep session open when `headless=False`

```python
# Clean up session (but NOT in headless=False mode)
if self.headless:
    await crawler.crawler_strategy.kill_session(session_id)
else:
    print("Keeping session open for inspection (headless=False)")
```

**Result**: Browser stays on the final search results page for inspection

## Data Field Selector Format

### Example: Ford Dealer Results

```json
{
  "name": {
    "selector": "h2.dealer-name",
    "type": "text"
  },
  "address": {
    "selector": "div.dealer-address",
    "type": "text"
  },
  "phone": {
    "selector": "a[href^='tel:']",
    "type": "href",
    "attribute": "href"
  },
  "website": {
    "selector": "a.website-link",
    "type": "href",
    "attribute": "href"
  },
  "distance": {
    "selector": "span.distance",
    "type": "text"
  }
}
```

### Selector Types

| Type | Usage | Example |
|------|-------|---------|
| `text` | Extract text content | `<h2>AutoNation Ford</h2>` → "AutoNation Ford" |
| `href` | Extract link URL from attribute | `<a href="tel:651-429-0123">` → "651-429-0123" |

## Passing Discovered Selectors

Discovered selectors are embedded in HTML and extracted by the main scraper:

```python
# In crawl4ai_scraper.py
selector_json = json.dumps(discovered_selectors)
html = f"<!-- DISCOVERED_SELECTORS: {selector_json} -->\n{html}"
return html

# In scrape_dealers.py
if html.startswith('<!-- DISCOVERED_SELECTORS:'):
    match = re.search(r'<!-- DISCOVERED_SELECTORS: (.+?) -->', html)
    discovered_selectors = json.loads(match.group(1))
    self.config['data_fields'] = discovered_selectors['data_fields']
```

## Testing

```bash
# Run with visible browser to see both discovery phases
python scrape_dealers.py --websites test_websites.txt --zip-codes "10001" --no-headless
```

**Watch for**:
1. Initial page load → Phase 1 LLM discovery
2. Form fill and submit
3. Search results appear → Phase 2 LLM discovery
4. Results expansion
5. Browser stays open showing final results

## Performance

| Operation | Time | Notes |
|-----------|------|-------|
| Phase 1 Discovery | ~3-5s | Analyzes form page |
| Form submission | ~2-3s | Fill + submit + wait |
| Phase 2 Discovery | ~3-5s | Analyzes results page |
| Result expansion | ~10-30s | Depends on # of dealers |
| **Total per zip** | ~20-45s | Adaptive and accurate |

## Future Improvements

1. **Cache Phase 2 selectors** per domain (like Phase 1)
2. **Confidence scoring** for selector quality
3. **Fallback patterns** if LLM discovery fails
4. **Parallel discovery** for multiple fields
5. **Visual validation** using screenshot analysis

## Conclusion

The two-phase LLM discovery ensures the scraper:
- ✅ Finds form elements on the initial page
- ✅ Understands how data is structured in search results
- ✅ Extracts information accurately from any website
- ✅ Adapts to different layouts and naming conventions
- ✅ Requires zero manual configuration

This is the most intelligent and adaptive approach to web scraping! 🎉
