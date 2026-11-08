+++
schema = "lite.card.v1"
id = "ex-41"
kind = "bugfix"
files = ["src/invoice/rounding.py", "tests/test_rounding.py"]
done_when = [
  "uv run pytest tests/test_rounding.py -k half_cent",
  "uv run pytest",
  "uv run mypy src",
]
+++

## Goal

`round_total` rounds half a cent to even, so 10.005 becomes 10.00. Invoices must round half a
cent away from zero, giving 10.01.

## Interfaces

None. `round_total(amount: Decimal) -> Decimal` keeps its signature.

## Context

`src/invoice/rounding.py`, lines 1-8 (the whole file):

```python
from decimal import ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")


def round_total(amount: Decimal) -> Decimal:
    """Round an invoice total to whole cents."""
    return amount.quantize(CENT, rounding=ROUND_HALF_EVEN)
```

`tests/test_rounding.py` holds `test_rounds_down_below_half` and `test_rounds_up_above_half`.
Add the new tests after them.

## Steps

1. In `tests/test_rounding.py`, add `test_half_cent_rounds_up`: 10.005 gives 10.01 and 10.015
   gives 10.02. Add `test_half_cent_rounds_away_from_zero_for_credits`: -10.005 gives -10.01.
   Run the first `done_when` command and see both fail.
2. In `round_total`, round half away from zero instead of to even, and drop the import that is
   no longer used.
3. Run every `done_when` command.

## Out of scope

- Currencies other than ones with cents, and the display formatting in `src/invoice/render.py`.
- If another caller depends on rounding to even, stop and report the task as blocked.
