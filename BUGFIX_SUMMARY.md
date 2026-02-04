# JavaScript Syntax Error Fix

## Issue

When running the scraper with LLM discovery, JavaScript syntax errors occurred:

```
[JS_EXEC]. ℹ Playwright execution error: Page.evaluate: SyntaxError: missing ) after argument list
```

## Root Cause

CSS selectors discovered by the LLM were not properly escaped before being inserted into JavaScript code. Selectors containing special characters (like single quotes, parentheses, or brackets) broke the JavaScript syntax.

**Example problematic selector**:
```javascript
// LLM returned: input[placeholder='Enter ZIP']
// Generated JavaScript (broken):
const input = document.querySelector('input[placeholder='Enter ZIP']');
//                                                     ↑ syntax error
```

## Solution

Added a robust JavaScript string escaping mechanism:

### 1. New Helper Method

```python
@staticmethod
def _escape_js_string(s: str) -> str:
    """Escape a string for safe use in JavaScript code."""
    if not s:
        return s
    # Escape single quotes, backslashes, and newlines
    return s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')
```

### 2. Applied to All Selectors

Updated all places where selectors are inserted into JavaScript:
- **Form fill**: `zip_input_selector = self._escape_js_string(discovered_selectors['zip_input'])`
- **Form submit**: `submit_button_selector = self._escape_js_string(discovered_selectors['submit_button'])`
- **View More**: `view_more_escaped = self._escape_js_string(view_more_selector)`
- **Virtual scroll**: `container_escaped = self._escape_js_string(container_selector)`

### 3. Result

All CSS selectors are now properly escaped before JavaScript injection:

```javascript
// Before: input[placeholder='Enter ZIP']
// After:  input[placeholder=\'Enter ZIP\']

const input = document.querySelector('input[placeholder=\'Enter ZIP\']');
//                                                     ↑ properly escaped
```

## Testing

To verify the fix works:

```bash
# Run with visible browser to see the interactions
python scrape_dealers.py --websites test_websites.txt --zip-codes "10001" --no-headless
```

Expected output:
- ✅ No JavaScript syntax errors
- ✅ Form fields are discovered and filled correctly
- ✅ Search submits successfully
- ✅ Dealer cards appear in results

## Files Changed

- `utils/crawl4ai_scraper.py`:
  - Added `_escape_js_string()` helper method
  - Updated 5 locations to use proper escaping

## Prevention

All future JavaScript string insertions should use `self._escape_js_string()` to prevent similar issues.

**Pattern to follow**:
```python
# Good ✓
selector = self._escape_js_string(discovered_selectors['field'])
js_code = f"document.querySelector('{selector}')"

# Bad ✗
js_code = f"document.querySelector('{discovered_selectors['field']}')"
```

## Related Improvements

While fixing this issue, also added:
1. Better error messages in LLM discovery
2. Improved logging for iframe detection
3. Consistent escape pattern across all methods
