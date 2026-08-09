#! /usr/bin/env python3

"""Main entry point"""

from argparse import ArgumentParser
import io
import sys

import pandas as pd


def try_datetime(series: pd.Series, min_success_rate: float = 0.9) -> pd.Series:
    """Try to convert a series to datetime; return converted series if it looks like dates."""
    if not (
        pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
    ):
        return series

    converted: pd.Series = pd.to_datetime(series, errors="coerce")

    # Only accept if most non-null values successfully converted
    success_rate: float = (
        converted.notna().sum() / series.notna().sum()
        if series.notna().sum() > 0
        else 0
    )

    if success_rate >= min_success_rate:
        return converted
    return series


def main():
    """Main entry point"""
    parser = ArgumentParser(
        prog="csv-util",
        description="A CLI utility to deal with CSV (and related) files.",
    )

    parser.add_argument("file", metavar="FILE", help='Input file, use "-" for stdin.')
    parser.add_argument(
        "-f",
        "--format",
        help="Output format",
        choices=["csv", "txt", "tsv", "md"],
        default="txt",
    )

    args = parser.parse_args()

    if args.file == "-":
        args.file = io.StringIO(sys.stdin.read())

    df = pd.read_csv(args.file, skip_blank_lines=True)

    # Attempt to convert to datetime
    for col in df.columns:
        df[col] = try_datetime(df[col])

    # Output
    if args.format == "csv":
        print(df.to_csv(index=False))
    elif args.format == "tsv":
        print(df.to_csv(index=False, sep="\t"))
    elif args.format == "txt":
        print(df.to_string(index=False))
    elif args.format == "md":
        print(df.to_markdown(index=False))


if __name__ == "__main__":
    main()
