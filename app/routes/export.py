"""CSV downloads of one car's data (/cars/{car_id}/export/...)."""

from fastapi import APIRouter, Response

from app.deps import DbSession, OwnedCar
from app.models import Car
from app.services import export as export_service

router = APIRouter(prefix="/cars/{car_id}/export")


def _download(content: bytes, car: Car, kind: str) -> Response:
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{export_service.filename(car, kind)}"',
            # Personal data: don't keep copies in shared or browser caches.
            "Cache-Control": "no-store",
        },
    )


@router.get("/service.csv")
def export_service_entries(car: OwnedCar, db: DbSession) -> Response:
    return _download(export_service.service_csv(db, car), car, "serwis")


@router.get("/fuel.csv")
def export_fuel_entries(car: OwnedCar, db: DbSession) -> Response:
    return _download(export_service.fuel_csv(db, car), car, "tankowania")
