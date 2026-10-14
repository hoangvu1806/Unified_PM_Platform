# Warehouse Material Request Rules

## Rules
- Each material request needs exactly one human approver.
- SKU on the request must match warehouse stock identity; no silent substitution.
- Negative stock is not allowed after pick.

## Constraint
- MSDS constraints block pick when missing.
