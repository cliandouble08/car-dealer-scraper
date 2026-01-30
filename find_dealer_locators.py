# First, install the library: pip install duckduckgo-search

from duckduckgo_search import DDGS
import time


def find_dealer_locators(brands):
    """
    Search for official dealer locator pages for a list of car brands.

    Args:
        brands: List of brand names to search for

    Returns:
        Dictionary mapping brand names to their dealer locator URLs
    """
    results = {}

    print(f"{'Brand':<20} | {'Locator URL'}")
    print("-" * 60)

    with DDGS() as ddgs:
        for brand in brands:
            query = f"{brand} official dealer locator"
            # We fetch 1 result for the most relevant hit
            search_results = list(ddgs.text(query, max_results=1))

            if search_results:
                url = search_results[0]['href']
                results[brand] = url
                print(f"{brand:<20} | {url}")
            else:
                results[brand] = None
                print(f"{brand:<20} | Not Found")

            # Sleep briefly to avoid hitting rate limits
            time.sleep(1)

    return results


if __name__ == "__main__":
    # Example Usage
    car_brands = ["Toyota", "Ford", "Tesla", "Lucid Motors", "Ferrari"]
    locator_urls = find_dealer_locators(car_brands)
