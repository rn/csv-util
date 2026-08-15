#! /usr/bin/env python3

"""Main entry point"""

from argparse import ArgumentParser
import io
import re
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


# Matches contains(Column, 'substring'[, case=True|False])
_CONTAINS_RE = re.compile(
    r"contains\(\s*(\w+)\s*,\s*('[^']*'|\"[^\"]*\")\s*(?:,\s*case\s*=\s*(True|False))?\s*\)"
)

# Matches bare dates like 2026-01-01, but not ones already quoted or glued
# to other word characters.
_DATE_RE = re.compile(r"(?<![\"'\w])\d{4}-\d{2}-\d{2}(?![\"'\w])")


def filter_rows(df: pd.DataFrame, expr: str) -> pd.DataFrame:
    """Filter dataframe rows using pandas query"""
    # add quotes around dates so that query works
    safe_expr = _DATE_RE.sub(lambda m: f"'{m.group(0)}'", expr)

    # rewrite "contains" to an expression understood by "qeury"
    def _rewrite_contains(match: "re.Match[str]") -> str:
        column, substring, case = (
            match.group(1),
            match.group(2),
            match.group(3) or "False",
        )
        return f"{column}.astype('string').str.contains({substring}, case={case}, na=False, regex=False)"

    safe_expr = _CONTAINS_RE.sub(_rewrite_contains, safe_expr)

    try:
        return df.query(safe_expr, engine="python")
    except Exception as exc:  # pandas raises several different error types
        print(f"Error evaluating row filter '{expr}': {exc}", file=sys.stderr)
        sys.exit(1)


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
    filter_args.add_argument(
        "-r",
        "--rows",
        help=(
            "Filter rows using a boolean expression, e.g. 'Date > 2026-01-01 & Transaction >= 0.0'. Use 'contains(Column, 'text')' for substring match. This is a wrapper around pandas 'query()' "
        ),
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
    trans_args.add_argument(
        "--sample",
        help="Re-sample on a time/date based column. Argument is <column>:<freq>, where 'freq' is accepted by pandas resample()",
        default=None,
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

    if args.rows is not None:
        df = filter_rows(df, args.rows)

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

    if args.sample is not None:
        col, freq = args.sample.split(":")
        df = df.resample(freq, on=col).last().reset_index()

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
