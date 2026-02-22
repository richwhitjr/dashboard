"""Safe SQL query builders that validate column names against explicit allowlists."""


def safe_update_query(
    table: str,
    fields_dict: dict,
    allowed_columns: set[str],
    extra_set_clauses: list[str] | None = None,
) -> tuple[str, list]:
    """Build a parameterized UPDATE SET clause, validating all column names.

    Args:
        table: The table name (must be a hardcoded literal from the caller).
        fields_dict: {column_name: value} dict, typically from model_dump(exclude_unset=True).
        allowed_columns: Explicit set of column names permitted for this table.
        extra_set_clauses: Additional literal SET clauses like "updated_at = datetime('now')"
                          or "updated_at = ?" (caller must append the value to params).

    Returns:
        (set_clause_string, params_list) ready for use in:
        db.execute(f"UPDATE {table} SET {set_clause} WHERE id = ?", params + [row_id])

    Raises:
        ValueError: If any column name is not in allowed_columns.
    """
    clauses = []
    params = []

    for col, value in fields_dict.items():
        if col not in allowed_columns:
            raise ValueError(f"Disallowed column: {col}")
        clauses.append(f"{col} = ?")
        params.append(value)

    if extra_set_clauses:
        clauses.extend(extra_set_clauses)

    set_clause = ", ".join(clauses)
    return set_clause, params
