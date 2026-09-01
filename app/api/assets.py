from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import dashboard
from app.models import Operator, Site
from app.schemas import AssetDetail, AssetOut, OperatorOut, SiteOut

router = APIRouter(tags=["assets"])


@router.get("/assets", response_model=list[AssetOut])
def list_assets(
    status: str | None = Query(None, description="AVAILABLE|RENTED|IN_USE|IDLE|OVERDUE|UNACCOUNTED"),
    site_id: str | None = None,
    type: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    return dashboard.list_assets(db, status=status, site_id=site_id, equipment_type=type, search=search)


@router.get("/assets/{equipment_id}", response_model=AssetDetail)
def asset_detail(equipment_id: str, db: Session = Depends(get_db)):
    return dashboard.asset_detail(db, equipment_id.upper())


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return dashboard.overview(db)


@router.get("/sites", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db)):
    return list(db.scalars(select(Site).order_by(Site.site_id)))


@router.get("/operators", response_model=list[OperatorOut])
def list_operators(db: Session = Depends(get_db)):
    return list(db.scalars(select(Operator).order_by(Operator.operator_id)))
