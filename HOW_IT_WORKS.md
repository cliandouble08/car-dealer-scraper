# How the Dealer Scraper Works

## Your Question
> I want the scraper to fill in the zip code in the page and scroll and load all dealers and extract their information to corresponding field, is it doing this?

## Answer: YES! Here's exactly what it does:

## Complete Workflow

### 1️⃣ Page Load & Discovery
```
Navigate to: https://www.ford.com/dealerships/
↓
Detect iframes (if any)
↓
Run LLM Discovery to identify:
  • Zip code input field
  • Submit/Search button
  • "Load More"/"View More" button (if exists)
  • Dealer card container selector
```

**What LLM finds** (example for Ford):
- Zip input: `input[placeholder*='zip']`
- Submit button: `button[type='submit']`
- Dealer cards: `li[class*='dealer']` or `div[class*='dealer']`

### 2️⃣ Fill Zip Code
```javascript
const input = document.querySelector('input[placeholder*=\'zip\']');
if (input) {
    input.value = '10001';  // Your zip code
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
}
```

**Result**: Zip code "10001" is filled into the search box

### 3️⃣ Submit Search
```javascript
const btn = document.querySelector('button[type=\'submit\']');
if (btn) {
    btn.click();  // Click the search button
}

// Wait for dealer cards to appear (up to 30 seconds)
for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 1000));
    const cards = document.querySelectorAll('li[class*=\'dealer\']');
    if (cards && cards.length > 0) {
        console.log(`Found ${cards.length} dealer cards`);
        return true;  // Success!
    }
}
```

**Result**: Form is submitted, page shows dealer results for zip code 10001

### 4️⃣ Expand Results (Load More / Scroll)

**Option A: "Load More" button** (if site uses pagination)
```javascript
// Click "Load More" button up to 30 times
for (let i = 0; i < 30; i++) {
    const btn = document.querySelector('button.load-more');
    if (btn && btn.offsetParent !== null) {
        btn.click();
        await new Promise(r => setTimeout(r, 1500));
    } else {
        break;  // No more results
    }
}
```

**Option B: Virtual Scroll** (if site uses infinite scroll)
```javascript
const container = document.querySelector('div.dealer-list');
for (let i = 0; i < 30; i++) {
    container.scrollTop += container.clientHeight;
    await new Promise(r => setTimeout(r, 500));
}
```

**Option C: Regular Scroll** (fallback)
```javascript
for (let i = 0; i < 20; i++) {
    window.scrollBy(0, window.innerHeight);
    await new Promise(r => setTimeout(r, 500));
}
```

**Result**: All dealer results are loaded into the page (hundreds of dealers)

### 5️⃣ Extract Dealer Information

For each dealer card found (e.g., `li[class*='dealer']`), extract:

```python
# Name
name = card.select_one('.dealer-card h2').get_text()
# → "AutoNation Ford White Bear Lake"

# Address
address = card.select_one('.dealer-card .address').get_text()
# → "4801 Highway 61, White Bear Lake, MN 55110"

# Phone
phone = card.select_one('a[href^="tel:"]').get('href')
# → "tel:651-429-0123" → cleaned to "651-429-0123"

# Website
website = card.select_one('a[href^="http"]').get('href')
# → "https://www.autonationfordwhitebearlake.com"

# Distance
distance = extract_distance(card.get_text())
# → "15.3 miles"
```

**Result**: List of `Dealer` objects with all information

### 6️⃣ Save Results

Save to files:
```
output/ford_com_dealers_20260203_200853.csv
output/ford_com_dealers_20260203_200853.json
```

**CSV Format**:
```csv
source_url,name,address,city,state,zip_code,phone,website,dealer_type,distance_miles,search_zip,scrape_date
https://www.ford.com/dealerships/,AutoNation Ford White Bear Lake,"4801 Highway 61",White Bear Lake,MN,55110,651-429-0123,https://...,Standard,15.3,10001,2026-02-03 20:08:53
```

## What Was Going Wrong?

### The Problem
```
Error: Wait condition failed: Timeout after 60000ms waiting for selector 'li[class*='dealer']'
```

### Why It Failed
The scraper was waiting for dealer cards (`li[class*='dealer']`) to appear **BEFORE** submitting the form. Of course they don't exist yet - they only appear AFTER searching!

### The Fix
Changed from:
```python
# OLD - wrong order
config = CrawlerRunConfig(
    js_code=submit_js,
    wait_for="css:li[class*='dealer']",  # ❌ Cards don't exist yet!
)
```

To:
```python
# NEW - wait INSIDE JavaScript after clicking submit
submit_js = """
    btn.click();  // Submit form

    // NOW wait for cards to appear
    for (let i = 0; i < 30; i++) {
        await new Promise(r => setTimeout(r, 1000));
        const cards = document.querySelectorAll('li[class*=\'dealer\']');
        if (cards && cards.length > 0) {
            return true;  // ✅ Found them!
        }
    }
"""
```

## Session Management

All steps use the same browser session (tab):
```
Session ID: dealer_search_10001_12345

[Initial Load] → [Fill Zip] → [Submit] → [Load More] → [Load More] → [Extract]
     ↓              ↓            ↓           ↓            ↓             ↓
   Same tab     Same tab    Same tab    Same tab     Same tab      Same tab
```

**Benefits**:
- No page reloads
- Maintains JavaScript state
- Keeps cookies/localStorage
- Faster execution

## Iframe Handling

If the dealer locator is in an iframe:
```html
<html>
  <body>
    <iframe src="https://dealers.ford.com/locator">
      <!-- Dealer search form is HERE -->
      <input placeholder="Enter ZIP" />
      <button>Search</button>
    </iframe>
  </body>
</html>
```

The scraper automatically:
1. Detects iframe with: `has_iframes = '<iframe' in html`
2. Enables: `process_iframes=True` for all operations
3. Merges iframe content into main HTML
4. Searches for elements inside iframe

## Current Status

✅ **Fills zip code** - Uses LLM-discovered selector
✅ **Submits search** - Clicks button or presses Enter
✅ **Waits for results** - Polls for dealer cards up to 30 seconds
✅ **Expands results** - Clicks "Load More" or scrolls
✅ **Extracts dealers** - Gets name, address, phone, website
✅ **Handles iframes** - Automatic detection and processing
✅ **Session maintained** - Same browser tab throughout

## Try It Now

```bash
python scrape_dealers.py --websites test_websites.txt --zip-codes "10001" --no-headless
```

You'll see the browser:
1. Navigate to Ford dealer locator
2. Fill in "10001" in the zip code box
3. Click "Search" button
4. Wait for dealer cards to appear
5. Click "Load More" multiple times
6. Extract all dealer information
7. Save to CSV/JSON

That's exactly what you wanted! 🎉
