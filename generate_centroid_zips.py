#!/usr/bin/env python3
"""
Generate Centroid Zip Codes for Nationwide Coverage (High Overlap)

Creates a list of zip codes to provide 100% efficient nationwide coverage
for dealer scraping.

IMPROVEMENT:
This version uses a tight-packing algorithm. To guarantee no blank spots
at the "corners" of the circles, it calculates centroids based on an
inscribed square logic (Radius / sqrt(2)).

Usage:
    python generate_centroid_zips.py
    python generate_centroid_zips.py --radius 50 --output centroid_zips.txt
    python generate_centroid_zips.py --radius 75
"""

import argparse
import math
from typing import List
from dataclasses import dataclass

import pgeocode
import pandas as pd


@dataclass
class ZipInfo:
    """Represents a zip code with its coordinates."""
    zipcode: str
    lat: float
    lng: float
    city: str
    state: str


def haversine_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in miles between two coordinates using Haversine formula."""
    R = 3959  # Earth's radius in miles

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng/2)**2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


def load_all_zipcodes() -> List[ZipInfo]:
    """Load all US zip codes from pgeocode library."""
    print("Loading US zip code database...")

    # Initialize US postal code lookup
    nomi = pgeocode.Nominatim('us')

    # pgeocode stores data internally - access the dataframe
    df = nomi._data

    all_zips = []
    for _, row in df.iterrows():
        zipcode = str(row['postal_code']).zfill(5)
        lat = row['latitude']
        lng = row['longitude']
        city = row.get('place_name', '')
        state = row.get('state_code', '')

        # Skip if missing coordinates
        if pd.isna(lat) or pd.isna(lng):
            continue

        # Ensure string types for city and state
        city = str(city) if not pd.isna(city) else ''
        state = str(state) if not pd.isna(state) else ''

        all_zips.append(ZipInfo(
            zipcode=zipcode,
            lat=float(lat),
            lng=float(lng),
            city=city,
            state=state
        ))

    print(f"Loaded {len(all_zips)} zip codes")
    return all_zips


def select_centroid_zips(all_zips: List[ZipInfo], target_radius: float) -> List[ZipInfo]:
    """
    Select centroid zip codes using a high-overlap greedy algorithm.

    CRITICAL CHANGE:
    To ensure no empty spots at the corners of the circles, we must space
    centroids closer than the target radius.

    Formula: Spacing = Target_Radius / sqrt(2)
    Example: For 50mi coverage, we space points ~35.3mi apart.
    """
    # Calculate the tighter spacing required to cover corners
    spacing_radius = target_radius / math.sqrt(2)

    print(f"Target Coverage Radius: {target_radius} miles")
    print(f"Calculated Grid Spacing: {spacing_radius:.2f} miles (ensures corner coverage)")
    print(f"Selecting centroids...")

    # Sort geographically for consistent ordering
    sorted_zips = sorted(all_zips, key=lambda z: (str(z.state or ''), z.lat, z.lng))

    centroids: List[ZipInfo] = []

    # Use spatial indexing for faster lookup
    # Grid cell size is derived from degrees (approx 69 miles per lat degree)
    # We use a cell size slightly larger than spacing to check neighbors efficiently
    grid_size_deg = spacing_radius / 69.0
    centroid_grid = {}

    def get_grid_key(lat: float, lng: float) -> tuple:
        return (int(lat / grid_size_deg), int(lng / grid_size_deg))

    def get_nearby_centroids(lat: float, lng: float) -> List[ZipInfo]:
        """Retrieve centroids from the same grid cell and all 8 neighbors."""
        center_key = get_grid_key(lat, lng)
        nearby = []
        for dlat in [-1, 0, 1]:
            for dlng in [-1, 0, 1]:
                key = (center_key[0] + dlat, center_key[1] + dlng)
                if key in centroid_grid:
                    nearby.extend(centroid_grid[key])
        return nearby

    for i, zip_info in enumerate(sorted_zips):
        if i % 10000 == 0:
            print(f"  Processed {i}/{len(sorted_zips)} candidates...")

        # Check against existing centroids
        # We use spacing_radius here. If a zip is within spacing_radius of an existing centroid,
        # it is "covered" for the purpose of spacing, so we skip it.
        # This forces the next selected centroid to be at least spacing_radius away.
        is_covered = False
        candidates = get_nearby_centroids(zip_info.lat, zip_info.lng)

        for centroid in candidates:
            dist = haversine_distance(zip_info.lat, zip_info.lng, centroid.lat, centroid.lng)
            if dist <= spacing_radius:
                is_covered = True
                break

        if not is_covered:
            centroids.append(zip_info)
            key = get_grid_key(zip_info.lat, zip_info.lng)
            if key not in centroid_grid:
                centroid_grid[key] = []
            centroid_grid[key].append(zip_info)

    print(f"Selected {len(centroids)} centroids with {spacing_radius:.2f}mi spacing.")
    print(f"This guarantees full coverage for {target_radius}mi radius scans.")

    return centroids


def save_centroid_zips(centroids: List[ZipInfo], output_file: str):
    """Save centroid zip codes to a file compatible with scrape_dealers.py."""

    # Sort by state then by city for organized output
    sorted_centroids = sorted(centroids, key=lambda z: (str(z.state or ''), str(z.city or '')))

    with open(output_file, 'w') as f:
        f.write(f"# Centroid Zip Codes (High Overlap Mode)\n")
        f.write(f"# Total Count: {len(centroids)}\n")
        f.write(f"# Generated to guarantee full coverage within specified radius.\n")
        f.write(f"#\n")
        f.write(f"# Usage: python scrape_dealers.py --brand ford --zip-file {output_file}\n")
        f.write(f"#\n")

        current_state = None
        for z in sorted_centroids:
            if z.state != current_state:
                current_state = z.state
                f.write(f"\n# {current_state}\n")

            f.write(f"{z.zipcode}\n")

    print(f"Saved to: {output_file}")


def save_stats(centroids: List[ZipInfo], output_file: str):
    """Save statistics about the centroid selection."""
    stats_file = output_file.replace('.txt', '_stats.txt')

    # Group by state
    by_state = {}
    for z in centroids:
        if z.state not in by_state:
            by_state[z.state] = []
        by_state[z.state].append(z)

    with open(stats_file, 'w') as f:
        f.write("Centroid Zip Code Statistics\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Total centroid zip codes: {len(centroids)}\n")
        f.write(f"States/territories covered: {len(by_state)}\n\n")

        f.write("By State:\n")
        f.write("-" * 30 + "\n")
        for state in sorted(by_state.keys()):
            zips = by_state[state]
            f.write(f"{state}: {len(zips)} centroids\n")

    print(f"Saved stats to: {stats_file}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate overlapping centroid zips for 100% coverage"
    )
    parser.add_argument(
        "--radius", type=float, default=50,
        help="Target scan radius in miles (default: 50)"
    )
    parser.add_argument(
        "--output", type=str, default="centroid_zip_codes.txt",
        help="Output file path (default: centroid_zip_codes.txt)"
    )
    parser.add_argument(
        "--include-military", action="store_true",
        help="Include military/overseas APO/FPO zip codes"
    )

    args = parser.parse_args()

    print(f"\nGenerating centroid zip codes with {args.radius}mi radius coverage")
    print(f"Using high-overlap algorithm to ensure 100% coverage\n")

    # Load all zip codes
    all_zips = load_all_zipcodes()

    # Filter out military/overseas zip codes unless explicitly included
    if not args.include_military:
        # Valid US state codes (50 states + DC)
        valid_states = {
            'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
            'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
            'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
            'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
            'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
            'DC'
        }
        original_count = len(all_zips)
        all_zips = [z for z in all_zips if z.state in valid_states]
        filtered = original_count - len(all_zips)
        if filtered > 0:
            print(f"Filtered out {filtered} military/overseas zip codes\n")

    if not all_zips:
        print("Error: No zip codes loaded. Make sure pgeocode is installed:")
        print("  pip install pgeocode")
        return

    # Select centroid zip codes
    centroids = select_centroid_zips(all_zips, args.radius)

    # Save results
    save_centroid_zips(centroids, args.output)
    save_stats(centroids, args.output)

    print(f"\n{'='*60}")
    print(f"COMPLETE: Generated {len(centroids)} centroid zip codes")
    print(f"{'='*60}")
    print(f"\nTo use with scrape_dealers.py:")
    print(f"  python scrape_dealers.py --brand ford --zip-file {args.output}")


if __name__ == "__main__":
    main()
