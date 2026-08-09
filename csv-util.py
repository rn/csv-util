#! /usr/bin/env python3

"""Main entry point"""

from argparse import ArgumentParser
import io
import sys
from typing import Optional

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


def comma_separated_list(value: str) -> Optional[list[str]]:
    """Convert string to list"""
    if value is None or value.strip() == "":
        return None
    return [item.strip() for item in value.split(",")]


def select_columns(strings: list[str], columns: list[str]) -> list[str]:
    """Return list of selected columns"""
    selected: list[str] = []

    for s in strings:
        if s in columns:
            # Direct name match
            if s not in selected:
                selected.append(s)
        else:
            try:
                idx = int(s)
                if 0 <= idx < len(columns) and columns[idx] not in selected:
                    selected.append(columns[idx])
            except ValueError:
                pass
    return selected


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
    parser.add_argument(
        "-c",
        "--columns",
        help="Select columns using a comma separated list. Elements can be column names of indices (starting as 0)",
        type=comma_separated_list,
        default=None,
    )

    args = parser.parse_args()

    if args.file == "-":
        args.file = io.StringIO(sys.stdin.read())

    df = pd.read_csv(args.file, skip_blank_lines=True)

    # Attempt to convert to datetime
    for col in df.columns:
        df[col] = try_datetime(df[col])

    if args.columns is not None:
        selected = select_columns(args.columns, df.columns.tolist())
        if len(selected) == 0:
            return
        df = df[selected]

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
