"""Importing a car's history from GarageLog CSV exports (/cars/{car_id}/import)."""

from fastapi import APIRouter, Request, Response, status

from app.deps import ActiveCar, CurrentUser, DbSession, UploadedFiles
from app.services import importing as importing_service
from app.services.importing import ImportReport
from app.templating import render

router = APIRouter(prefix="/cars/{car_id}/import")

# A file with many broken rows (e.g. the wrong file) would otherwise give a huge page.
MAX_ERRORS_SHOWN = 30


def _page(
    request: Request,
    user: CurrentUser,
    car: ActiveCar,
    report: ImportReport | None = None,
    message: str | None = None,
) -> Response:
    failed = message is not None or (report is not None and bool(report.errors))
    return render(
        request,
        "cars/import.html",
        {
            "user": user,
            "car": car,
            "report": report,
            "message": message,
            "max_errors": MAX_ERRORS_SHOWN,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if failed else status.HTTP_200_OK,
    )


@router.get("")
def import_page(request: Request, user: CurrentUser, car: ActiveCar) -> Response:
    return _page(request, user, car)


@router.post("")
def import_files(
    request: Request, user: CurrentUser, car: ActiveCar, db: DbSession, files: UploadedFiles
) -> Response:
    if not files:
        return _page(request, user, car, message="Wybierz co najmniej jeden plik CSV.")
    report = importing_service.import_csv_files(db, car, files)
    if not report.errors:
        db.commit()
    return _page(request, user, car, report=report)
