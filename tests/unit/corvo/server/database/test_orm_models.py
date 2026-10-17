from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from corvo.server.database.orm_models import Base


def test_constraints_get_predictable_names() -> None:
    # A copy of the convention, so the probe table stays out of Base's tables.
    metadata = MetaData(naming_convention=Base.metadata.naming_convention)
    probe = Table(
        "probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, unique=True),
    )

    ddl = str(CreateTable(probe).compile(dialect=postgresql.dialect()))

    assert "CONSTRAINT pk_probe PRIMARY KEY" in ddl
    assert "CONSTRAINT uq_probe_name UNIQUE" in ddl
