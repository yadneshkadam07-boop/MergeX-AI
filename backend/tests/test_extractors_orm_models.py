"""ORM model extraction: SQLAlchemy (both styles) and Prisma."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.extractors.orm_models import (
    OrmModel,
    extract_orm_models,
    sqlalchemy_type_family,
)


def write(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def models_of(root: Path) -> dict[str, OrmModel]:
    return {model.class_name: model for model in extract_orm_models(root).models}


class TestTypeFamilies:
    @pytest.mark.parametrize(
        ("type_name", "family"),
        [
            ("Integer", "integer"),
            ("BigInteger", "integer"),
            ("SmallInteger", "integer"),
            ("String", "string"),
            ("Text", "string"),
            ("Unicode", "string"),
            ("Numeric", "decimal"),
            ("Float", "float"),
            ("Boolean", "boolean"),
            ("DateTime", "datetime"),
            ("Date", "date"),
            ("JSON", "json"),
            ("Uuid", "uuid"),
            ("LargeBinary", "binary"),
        ],
    )
    def test_maps_sqlalchemy_types(self, type_name: str, family: str) -> None:
        assert sqlalchemy_type_family(type_name) == family

    def test_families_match_the_sql_side(self) -> None:
        """Both sides must reduce to the same vocabulary to be comparable."""
        from app.services.extractors.db_schema import canonical_type

        assert sqlalchemy_type_family("Numeric") == canonical_type("NUMERIC(10,2)")
        assert sqlalchemy_type_family("Integer") == canonical_type("INTEGER")
        assert sqlalchemy_type_family("String") == canonical_type("VARCHAR(64)")

    def test_numeric_and_integer_differ(self) -> None:
        assert sqlalchemy_type_family("Numeric") != sqlalchemy_type_family("Integer")


class TestClassicDeclarative:
    def test_extracts_a_model_and_its_fields(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Integer, String\n"
                    "class Product(Base):\n"
                    '    __tablename__ = "products"\n'
                    "    id = Column(Integer, primary_key=True)\n"
                    "    sku = Column(String(64), nullable=False, unique=True)\n"
                )
            },
        )

        model = models_of(tmp_path)["Product"]

        assert model.table_name == "products"
        assert model.location.line_start == 2
        assert model.fields["id"].is_primary_key
        assert model.fields["id"].location.line_start == 4
        assert model.fields["sku"].nullable is False
        assert model.fields["sku"].is_unique
        assert model.fields["sku"].type_family == "string"

    def test_requires_a_tablename(self, tmp_path: Path) -> None:
        """A mixin is not a mapped class, however it is named."""
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Integer\n"
                    "class TimestampMixin:\n"
                    "    created = Column(Integer)\n"
                )
            },
        )

        assert extract_orm_models(tmp_path).models == []

    def test_defaults_to_nullable(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, String\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    note = Column(String(10))\n"
                )
            },
        )

        assert models_of(tmp_path)["T"].fields["note"].nullable is True

    def test_a_primary_key_is_not_nullable(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Integer\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    id = Column(Integer, primary_key=True)\n"
                )
            },
        )

        assert models_of(tmp_path)["T"].fields["id"].nullable is False

    def test_reads_an_explicit_column_name(self, tmp_path: Path) -> None:
        """The attribute and the column need not share a name."""
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, String\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    '    code = Column("warehouse_code", String(16))\n'
                )
            },
        )

        field = models_of(tmp_path)["T"].fields["code"]

        assert field.column_name == "warehouse_code"
        assert field.type_family == "string"

    def test_reads_a_foreign_key(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, ForeignKey, Integer\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    '    supplier_id = Column(Integer, ForeignKey("suppliers.id"))\n'
                )
            },
        )

        field = models_of(tmp_path)["T"].fields["supplier_id"]

        assert field.foreign_key == "suppliers.id"
        assert field.type_family == "integer"

    def test_reads_a_bare_type(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Text\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    note = Column(Text)\n"
                )
            },
        )

        assert models_of(tmp_path)["T"].fields["note"].type_family == "string"

    def test_detects_a_default(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Integer\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    count = Column(Integer, default=0)\n"
                    "    other = Column(Integer, server_default='0')\n"
                )
            },
        )

        fields = models_of(tmp_path)["T"].fields

        assert fields["count"].has_default
        assert fields["other"].has_default

    def test_skips_dunder_attributes(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Integer\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    __table_args__ = (Index('x'),)\n"
                    "    id = Column(Integer, primary_key=True)\n"
                )
            },
        )

        assert list(models_of(tmp_path)["T"].fields) == ["id"]


class TestModernDeclarative:
    def test_extracts_mapped_column_fields(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy.orm import Mapped, mapped_column\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    id: Mapped[int] = mapped_column(primary_key=True)\n"
                    "    name: Mapped[str] = mapped_column(String(200))\n"
                )
            },
        )

        fields = models_of(tmp_path)["T"].fields

        assert fields["id"].type_family == "integer"
        assert fields["id"].is_primary_key
        assert fields["name"].type_family == "string"

    def test_an_optional_annotation_is_nullable(self, tmp_path: Path) -> None:
        """In 2.0 style the annotation decides nullability."""
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy.orm import Mapped, mapped_column\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    note: Mapped[str | None] = mapped_column()\n"
                    "    name: Mapped[str] = mapped_column()\n"
                )
            },
        )

        fields = models_of(tmp_path)["T"].fields

        assert fields["note"].nullable is True
        assert fields["name"].nullable is False

    def test_handles_the_optional_spelling(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from typing import Optional\n"
                    "from sqlalchemy.orm import Mapped, mapped_column\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    note: Mapped[Optional[str]] = mapped_column()\n"
                )
            },
        )

        assert models_of(tmp_path)["T"].fields["note"].nullable is True

    def test_an_explicit_nullable_overrides_the_annotation(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy.orm import Mapped, mapped_column\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    note: Mapped[str] = mapped_column(nullable=True)\n"
                )
            },
        )

        assert models_of(tmp_path)["T"].fields["note"].nullable is True

    def test_an_sqlalchemy_type_wins_over_the_annotation(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy.orm import Mapped, mapped_column\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    "    price: Mapped[float] = mapped_column(Numeric(10, 2))\n"
                )
            },
        )

        assert models_of(tmp_path)["T"].fields["price"].type_family == "decimal"


class TestRelationships:
    def test_extracts_a_relationship(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy.orm import relationship\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    '    supplier = relationship("Supplier", back_populates="products")\n'
                )
            },
        )

        relationship_ = models_of(tmp_path)["T"].relationships[0]

        assert relationship_.name == "supplier"
        assert relationship_.target_model == "Supplier"
        assert relationship_.back_populates == "products"
        assert relationship_.location.line_start == 4

    def test_a_relationship_is_not_a_field(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy.orm import relationship\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    '    supplier = relationship("Supplier")\n'
                )
            },
        )

        assert models_of(tmp_path)["T"].fields == {}

    def test_notes_whether_a_foreign_key_backs_the_relationship(self, tmp_path: Path) -> None:
        """A relationship with no FK anywhere is the schema-drift signature."""
        write(
            tmp_path,
            {
                "with_fk.py": (
                    "from sqlalchemy import Column, ForeignKey, Integer\n"
                    "from sqlalchemy.orm import relationship\n"
                    "class WithFk(Base):\n"
                    '    __tablename__ = "with_fk"\n'
                    '    supplier_id = Column(Integer, ForeignKey("suppliers.id"))\n'
                    '    supplier = relationship("Supplier")\n'
                ),
                "without_fk.py": (
                    "from sqlalchemy import Column, Integer\n"
                    "from sqlalchemy.orm import relationship\n"
                    "class WithoutFk(Base):\n"
                    '    __tablename__ = "without_fk"\n'
                    "    supplier_id = Column(Integer)\n"
                    '    supplier = relationship("Supplier")\n'
                ),
            },
        )

        models = models_of(tmp_path)

        assert models["WithFk"].relationships[0].foreign_keys_declared is True
        assert models["WithoutFk"].relationships[0].foreign_keys_declared is False


class TestPrisma:
    def test_extracts_a_model(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "prisma/schema.prisma": (
                    "model Product {\n"
                    "  id        Int      @id @default(autoincrement())\n"
                    "  sku       String   @unique\n"
                    "  note      String?\n"
                    "  price     Decimal\n"
                    "}\n"
                )
            },
        )

        model = models_of(tmp_path)["Product"]

        assert model.orm == "prisma"
        assert model.table_name == "Product"
        assert model.fields["id"].is_primary_key
        assert model.fields["id"].has_default
        assert model.fields["sku"].is_unique
        assert model.fields["sku"].nullable is False
        assert model.fields["note"].nullable is True
        assert model.fields["price"].type_family == "decimal"

    def test_field_lines_are_recorded(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"prisma/schema.prisma": ("model Product {\n  id   Int    @id\n  sku  String\n}\n")},
        )

        model = models_of(tmp_path)["Product"]

        assert model.fields["id"].location.line_start == 2
        assert model.fields["sku"].location.line_start == 3

    def test_reads_a_table_map(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {"prisma/schema.prisma": ('model Product {\n  id Int @id\n\n  @@map("products")\n}\n')},
        )

        assert models_of(tmp_path)["Product"].table_name == "products"

    def test_reads_a_column_map(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "prisma/schema.prisma": (
                    'model Product {\n  warehouseCode String @map("warehouse_code")\n}\n'
                )
            },
        )

        assert models_of(tmp_path)["Product"].fields["warehouseCode"].column_name == (
            "warehouse_code"
        )

    def test_a_model_typed_field_is_a_relation(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "prisma/schema.prisma": (
                    "model Product {\n"
                    "  id         Int      @id\n"
                    "  supplierId Int\n"
                    "  supplier   Supplier @relation(fields: [supplierId], references: [id])\n"
                    "}\n"
                )
            },
        )

        model = models_of(tmp_path)["Product"]

        assert "supplier" not in model.fields
        assert model.relationships[0].target_model == "Supplier"
        assert model.relationships[0].foreign_keys_declared is True

    def test_extracts_several_models(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "prisma/schema.prisma": (
                    "model A {\n  id Int @id\n}\n\nmodel B {\n  id Int @id\n}\n"
                )
            },
        )

        assert sorted(models_of(tmp_path)) == ["A", "B"]


class TestRobustness:
    def test_an_unparseable_file_is_reported(self, tmp_path: Path) -> None:
        write(tmp_path, {"models.py": "class T(:\n"})

        extraction = extract_orm_models(tmp_path)

        assert len(extraction.unparseable_files) == 1

    def test_by_table_indexes_models(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, Integer\n"
                    "class Product(Base):\n"
                    '    __tablename__ = "products"\n'
                    "    id = Column(Integer, primary_key=True)\n"
                )
            },
        )

        assert "products" in extract_orm_models(tmp_path).by_table()

    def test_field_by_column_finds_a_renamed_attribute(self, tmp_path: Path) -> None:
        write(
            tmp_path,
            {
                "models.py": (
                    "from sqlalchemy import Column, String\n"
                    "class T(Base):\n"
                    '    __tablename__ = "t"\n'
                    '    code = Column("warehouse_code", String(16))\n'
                )
            },
        )

        model = models_of(tmp_path)["T"]

        renamed = model.field_by_column("warehouse_code")
        assert renamed is not None
        assert renamed.name == "code"
        assert model.field_by_column("nope") is None

    def test_an_empty_tree_yields_nothing(self, tmp_path: Path) -> None:
        assert extract_orm_models(tmp_path).models == []
