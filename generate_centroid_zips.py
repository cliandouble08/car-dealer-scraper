#!/usr/bin/env python3
"""
Generate Centroid Zip Codes for Nationwide Coverage

Creates a list of zip codes spaced approximately 50 miles apart to provide
efficient nationwide coverage for dealer scraping. Uses a greedy algorithm
to select zip codes that maximize coverage while minimizing overlap.

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
    population: int


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
            state=state,
            population=0  # pgeocode doesn't include population
        ))

    print(f"Loaded {len(all_zips)} zip codes")
    return all_zips


def select_centroid_zips(all_zips: List[ZipInfo], radius_miles: float) -> List[ZipInfo]:
    """
    Select centroid zip codes using a greedy grid-based algorithm.

    Algorithm:
    1. Sort zip codes geographically (by state, then by lat/lng)
    2. For each zip, check if it's within radius of any already-selected centroid
    3. If not covered, add it as a new centroid

    This ensures good geographic coverage while maintaining spacing.
    """
    print(f"Selecting centroid zip codes with {radius_miles}mi spacing...")

    # Sort geographically for consistent ordering
    sorted_zips = sorted(all_zips, key=lambda z: (str(z.state or ''), z.lat, z.lng))

    centroids: List[ZipInfo] = []
    covered_count = 0

    # Use spatial indexing for faster lookup
    # Group centroids by rough lat/lng grid for efficiency
    centroid_grid = {}
    grid_size = radius_miles / 50  # Approximate degrees per grid cell

    def get_grid_key(lat: float, lng: float) -> tuple:
        return (int(lat / grid_size), int(lng / grid_size))

    def get_nearby_grid_keys(lat: float, lng: float) -> List[tuple]:
        """Get grid keys for the cell and its 8 neighbors."""
        base_lat = int(lat / grid_size)
        base_lng = int(lng / grid_size)
        keys = []
        for dlat in [-1, 0, 1]:
            for dlng in [-1, 0, 1]:
                keys.append((base_lat + dlat, base_lng + dlng))
        return keys

    for i, zip_info in enumerate(sorted_zips):
        if i % 5000 == 0:
            print(f"  Processing {i}/{len(sorted_zips)} zip codes, {len(centroids)} centroids selected...")

        # Check nearby grid cells for existing centroids
        is_covered = False
        nearby_keys = get_nearby_grid_keys(zip_info.lat, zip_info.lng)

        for key in nearby_keys:
            if key in centroid_grid:
                for centroid in centroid_grid[key]:
                    dist = haversine_distance(zip_info.lat, zip_info.lng, centroid.lat, centroid.lng)
                    if dist <= radius_miles:
                        is_covered = True
                        covered_count += 1
                        break
            if is_covered:
                break

        if not is_covered:
            centroids.append(zip_info)
            # Add to grid
            key = get_grid_key(zip_info.lat, zip_info.lng)
            if key not in centroid_grid:
                centroid_grid[key] = []
            centroid_grid[key].append(zip_info)

    print(f"Selected {len(centroids)} centroid zip codes")
    coverage_pct = (covered_count + len(centroids)) / len(sorted_zips) * 100
    print(f"Coverage: {covered_count + len(centroids)}/{len(sorted_zips)} ({coverage_pct:.1f}%) zip codes within {radius_miles}mi of a centroid")

    return centroids


def save_centroid_zips(centroids: List[ZipInfo], output_file: str, include_metadata: bool = True):
    """Save centroid zip codes to a file compatible with scrape_dealers.py."""

    # Sort by state then by city for organized output
    sorted_centroids = sorted(centroids, key=lambda z: (str(z.state or ''), str(z.city or '')))

    with open(output_file, 'w') as f:
        f.write(f"# Centroid Zip Codes for Nationwide Coverage\n")
        f.write(f"# Total: {len(centroids)} zip codes\n")
        f.write(f"# Each zip code covers approximately 50mi radius\n")
        f.write(f"# Generated for use with scrape_dealers.py\n")
        f.write(f"#\n")
        f.write(f"# Usage: python scrape_dealers.py --brand ford --zip-file {output_file}\n")
        f.write(f"#\n")

        current_state = None
        for z in sorted_centroids:
            if z.state != current_state:
                current_state = z.state
                f.write(f"\n# {current_state}\n")

            if include_metadata:
                f.write(f"{z.zipcode}  # {z.city}\n")
            else:
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
        description="Generate centroid zip codes for nationwide dealer scraping coverage"
    )
    parser.add_argument(
        "--radius", type=float, default=50,
        help="Radius in miles for coverage (default: 50)"
    )
    parser.add_argument(
        "--output", type=str, default="centroid_zip_codes.txt",
        help="Output file path (default: centroid_zip_codes.txt)"
    )
    parser.add_argument(
        "--no-metadata", action="store_true",
        help="Output zip codes only, without city/state comments"
    )
    parser.add_argument(
        "--domestic-only", action="store_true", default=True,
        help="Exclude military/overseas APO/FPO zip codes (default: True)"
    )
    parser.add_argument(
        "--include-military", action="store_true",
        help="Include military/overseas APO/FPO zip codes"
    )

    args = parser.parse_args()

    print(f"\nGenerating centroid zip codes with {args.radius}mi radius coverage\n")

    # Load all zip codes
    all_zips = load_all_zipcodes()

    # Filter out military/overseas zip codes unless explicitly included
    if not args.include_military:
        # Valid US state codes (50 states + DC + territories)
        valid_states = {
            'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
            'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
            'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
            'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
            'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
            'DC', 'PR', 'VI', 'GU', 'AS', 'MP'  # Include territories
        }
        original_count = len(all_zips)
        all_zips = [z for z in all_zips if z.state in valid_states]
        filtered = original_count - len(all_zips)
        if filtered > 0:
            print(f"Filtered out {filtered} military/overseas zip codes")

    if not all_zips:
        print("Error: No zip codes loaded. Make sure pgeocode is installed:")
        print("  pip install pgeocode")
        return

    # Select centroid zip codes
    centroids = select_centroid_zips(all_zips, args.radius)

    # Save results
    save_centroid_zips(centroids, args.output, include_metadata=not args.no_metadata)
    save_stats(centroids, args.output)

    print(f"\n{'='*60}")
    print(f"COMPLETE: Generated {len(centroids)} centroid zip codes")
    print(f"{'='*60}")
    print(f"\nTo use with scrape_dealers.py:")
    print(f"  python scrape_dealers.py --brand ford --zip-file {args.output}")


if __name__ == "__main__":
    main()
