"""The same exact metadata predicate is applied before both recall channels."""

from sqlalchemy import and_, or_, select

from src.domain.document_search import DocumentSearchFilters


def metadata_predicates(table, filters: DocumentSearchFilters):
    predicates = []
    for key in ("engineering_model", "applicable_revision", "document_type"):
        value = getattr(filters, key)
        if value is not None:
            predicates.append(table.c[key] == value)
    if filters.effective_on is not None:
        predicates.extend([
            table.c.effective_from <= filters.effective_on,
            or_(table.c.effective_to.is_(None), table.c.effective_to >= filters.effective_on),
        ])
    return predicates


def apply_document_filters(statement, documents, business_metadata, filters: DocumentSearchFilters):
    if filters.upload_version is not None:
        statement = statement.where(documents.c.version == filters.upload_version)
    predicates = metadata_predicates(business_metadata, filters)
    if predicates:
        statement = statement.where(select(business_metadata.c.document_id).where(and_(
            business_metadata.c.document_id == documents.c.id, *predicates,
        )).exists())
    return statement


def vector_filter_sql(filters: DocumentSearchFilters) -> tuple[list[str], dict]:
    clauses, params, metadata = [], {}, []
    if filters.upload_version is not None:
        clauses.append("d.version = :filter_upload_version")
        params["filter_upload_version"] = filters.upload_version
    for key in ("engineering_model", "applicable_revision", "document_type"):
        value = getattr(filters, key)
        if value is not None:
            metadata.append(f"m.{key} = :filter_{key}")
            params[f"filter_{key}"] = value
    if filters.effective_on is not None:
        metadata.extend([
            "m.effective_from <= :filter_effective_on",
            "(m.effective_to IS NULL OR m.effective_to >= :filter_effective_on)",
        ])
        params["filter_effective_on"] = filters.effective_on
    if metadata:
        clauses.append("EXISTS (SELECT 1 FROM document_business_metadata m WHERE m.document_id = d.id AND "
                       + " AND ".join(metadata) + ")")
    return clauses, params
