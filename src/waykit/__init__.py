from .models import (Feature, FeatureCollection, FeatureProperties, PointGeometry)
import argparse
from .openstreetmap_provider import gpx_to_features

from pathlib import Path


def write_feature_collection(path, fc: FeatureCollection) -> None:

    # Write to file
    Path(path).write_text(fc.model_dump_json(indent=2), encoding="utf-8")

def read_feature_collection(path) -> FeatureCollection:
    # Read from file
    raw = Path(path).read_text(encoding="utf-8")
    fc2 = FeatureCollection.model_validate_json(raw)

    # Access features
    for f in fc2.features:
        print(f.id, f.properties.name, f.properties.kind, f.geometry.coordinates)


def main():
    ap = argparse.ArgumentParser(description="Extract nearby peaks and huts from OSM around a GPX route.")
    ap.add_argument("gpx", help="Path to input GPX file")
    ap.add_argument("-o", "--out", default="nearby_features.geojson", help="Output GeoJSON file")
    ap.add_argument("--margin-km", type=float, default=2.0, help="BBox margin around GPX (km)")
    ap.add_argument("--distance-m", type=float, default=500.0, help="Max distance from GPX points to keep features (m)")
    ap.add_argument("--user-agent", default="waykit/0.1 (example script; contact: you@example.com)", help="HTTP User-Agent for Overpass")
    args = ap.parse_args()

    fc = gpx_to_features(
        gpx_path=args.gpx,
        margin_km=args.margin_km,
        distance_m=args.distance_m,
        user_agent=args.user_agent,
    )

    # Write GeoJSON
    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(fc.model_dump_json(indent=2))
    print(f"Wrote {out_path} with {len(fc.features)} features.")


if __name__ == "__main__":
    main()