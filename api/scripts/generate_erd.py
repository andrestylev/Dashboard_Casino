"""Generate docs/erd.md (a Mermaid ER diagram) straight from the SQLAlchemy models.

Run from the repo root:
    python api/scripts/generate_erd.py                 # rewrites docs/erd.md
    python api/scripts/generate_erd.py --no-attributes # prints relationships only
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base  # noqa: E402

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "erd.md"

TYPE_NAMES = {
    "BigInteger": "bigint", "Integer": "int", "SmallInteger": "smallint", "String": "varchar",
    "Text": "text", "Numeric": "numeric", "Boolean": "bool", "DateTime": "timestamptz",
    "Date": "date", "JSONB": "jsonb", "INET": "inet", "UUID": "uuid", "Enum": "enum",
}  # fmt: skip

# daily_game_stats is a materialized view (see migration 0001), so it is not in the metadata.
VIEW_COLUMNS = [
    ("date", "stat_date"), ("int", "game_id"), ("int", "total_bets"), ("int", "unique_players"),
    ("numeric", "total_staked"), ("numeric", "total_paid"), ("numeric", "ggr"),
]  # fmt: skip


def build(attributes: bool) -> str:
    lines = ["erDiagram"]
    tables = sorted(Base.metadata.tables.values(), key=lambda t: t.name)

    for table in tables:
        for fk in sorted(table.foreign_key_constraints, key=lambda c: c.columns.keys()):
            cols = list(fk.columns)
            nullable = any(c.nullable for c in cols)
            one_to_one = len(cols) == 1 and (cols[0].unique or cols[0].primary_key)
            left = "|o" if nullable else "||"  # how many parents per child
            right = "o|" if one_to_one else "o{"  # how many children per parent
            lines.append(
                f"  {fk.referred_table.name} {left}--{right} {table.name} : {cols[0].name}"
            )
    lines.append('  games ||--o{ daily_game_stats : "game_id (view)"')

    if attributes:
        for table in tables:
            lines.append(f"  {table.name} {{")
            for col in table.columns:
                keys = []
                if col.primary_key:
                    keys.append("PK")
                if col.foreign_keys:
                    keys.append("FK")
                if col.unique and not col.primary_key:
                    keys.append("UK")
                py_type = type(col.type).__name__
                type_name = TYPE_NAMES.get(py_type, py_type.lower())
                key_text = f" {', '.join(keys)}" if keys else ""
                lines.append(f"    {type_name} {col.name}{key_text}")
            lines.append("  }")
        lines.append("  daily_game_stats {")
        lines.extend(f"    {t} {n}" for t, n in VIEW_COLUMNS)
        lines.append("  }")
    return "\n".join(lines)


DOC_TEMPLATE = """# Database diagram

> Generated from the models by `python api/scripts/generate_erd.py`. Do not edit by hand.

How to read the crow's feet: look at the symbol **next to the other table**.
`||` exactly one, `|o` zero or one, `o{` zero or many, `o|` zero or one (one-to-one side).

```mermaid
{diagram}
```

## Conventions

- Identifiers: `bigint` identity keys (small lookup tables use `smallint`/`int`).
- Money: `numeric(12,2)`; wallet balance `numeric(14,2)`.
  One currency for the whole casino (not stored per row).
- Timestamps: `timestamptz`, UTC.
- Enumerations: `varchar` + CHECK constraint (easier to migrate than native PostgreSQL enums).
- `players` and `admin_users` are never deleted (deactivate/close instead); financial and gameplay
  foreign keys are `ON DELETE RESTRICT`.
- `daily_game_stats` is a **materialized view** over `bets`; refresh it with
  `REFRESH MATERIALIZED VIEW CONCURRENTLY daily_game_stats;`.
- Wallet is optional at the database level (`players ||--o| wallets`): the application creates one
  wallet per player.
"""

if __name__ == "__main__":
    if "--no-attributes" in sys.argv:
        print(build(attributes=False))
    else:
        DOC_PATH.parent.mkdir(exist_ok=True)
        diagram = build(attributes=True)
        DOC_PATH.write_text(DOC_TEMPLATE.replace("{diagram}", diagram) + "\n", encoding="utf-8")
        print(f"Wrote {DOC_PATH}")
