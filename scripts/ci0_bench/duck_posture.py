# File: scripts/ci0_bench/duck_posture.py
"""CI.0 part 1: proves the locked-down DuckDB configuration over Arrow tables (what it allows, what it refuses).
A throwaway probe, not product code; its output is quoted in plans/phase-4-ci0-findings.md section 3.
"""

import duckdb
import pyarrow as pa

print("duckdb", duckdb.__version__)
con = duckdb.connect(
    ":memory:",
    config={
        "enable_external_access": False,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    },
)
con.execute("SET lock_configuration=true")
t = pa.table({"a": [1, 2, 3, 4], "b": ["x", "y", "x", None]})
con.register("t", t)
print(
    "group-by:",
    con.execute(
        "select b, sum(a) s, median(a) m from t group by b order by b nulls last"
    ).fetchall(),
)
print(
    "approx_count_distinct:",
    con.execute("select approx_count_distinct(b) from t").fetchall(),
)
for sql in [
    "select * from read_parquet('x.parquet')",
    "select * from read_csv('x.csv')",
    "copy t to 'out.csv'",
    "install httpfs",
    "load httpfs",
    "set enable_external_access=true",
    "attach 'x.db'",
    "select * from glob('*')",
]:
    try:
        con.execute(sql)
        print("ALLOWED :", sql)
    except duckdb.Error as e:
        print("BLOCKED :", sql, "->", type(e).__name__)
