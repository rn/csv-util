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


def args_comma_separated_list(value: str) -> Optional[list[str]]:
    """Convert string to list"""
    if value is None or value.strip() == "":
        return None
    return [item.strip() for item in value.split(",")]


def cols_select(strings: list[str], columns: list[str]) -> list[str]:
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

    filter_args = parser.add_argument_group("Filter arguments")
    filter_args.add_argument(
        "-c",
        "--columns",
        help="Select columns using a comma separated list. Elements can be column names or indices (starting as 0)",
        type=args_comma_separated_list,
        default=None,
    )

    trans_args = parser.add_argument_group("Transformation arguments")
    trans_args.add_argument(
        "--sort",
        help="Sort csv file based on comma separated list of columns. Elements can be column names or indices (starting as 0)",
        type=args_comma_separated_list,
        default=None,
    )
    trans_args.add_argument(
        "--sort-dir",
        help="Sort direction. A list of 'a' (ascending) or 'd' (descending). Default ascending",
        type=args_comma_separated_list,
        default=["a"],
    )

    out_args = parser.add_argument_group("Output arguments")
    out_args.add_argument(
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

    #
    # Filtering
    #
    if args.columns is not None:
        selected = cols_select(args.columns, df.columns.tolist())
        if len(selected) > 0:
            df = df[selected]

    #
    # Transform
    #
    if args.sort is not None:
        selected = cols_select(args.sort, df.columns.tolist())
        if len(selected) > 0:
            order = []
            for i in range(len(selected)):
                dir_value = (
                    args.sort_dir[i] if i < len(args.sort_dir) else args.sort_dir[-1]
                )
                order.append("a" in dir_value)
            df.sort_values(by=selected, ascending=order, inplace=True)

    #
    # Output
    #
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
