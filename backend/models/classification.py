from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, CommonColumnsMixin, str_enum
from backend.models.enums import Category, ClassificationProvider, Impact, Priority, Urgency


class Classification(CommonColumnsMixin, Base):
    __tablename__ = "classifications"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    provider: Mapped[ClassificationProvider] = mapped_column(
        str_enum(ClassificationProvider, "provider")
    )
    category_suggested: Mapped[Category] = mapped_column(str_enum(Category, "category_suggested"))
    impact_suggested: Mapped[Impact] = mapped_column(str_enum(Impact, "impact_suggested"))
    urgency_suggested: Mapped[Urgency] = mapped_column(str_enum(Urgency, "urgency_suggested"))
    priority_computed: Mapped[Priority] = mapped_column(str_enum(Priority, "priority_computed"))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    review_required: Mapped[bool]
    rationale: Mapped[str | None] = mapped_column(String(200))
    rules_version: Mapped[str] = mapped_column(String(20))
    model_version: Mapped[str | None] = mapped_column(String(100))
    validated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
