"""Miscellaneous vehicle expenses (insurance, tax, parking, tolls, fines, …)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense, ExpenseCategory, User, Vehicle
from app.security import require_user
from app.templating import render

router = APIRouter(prefix="/vehicles/{vehicle_id}/expenses", tags=["expenses"])


def _get_owned_vehicle(db: Session, user: User, vehicle_id: int) -> Vehicle:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None or vehicle.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


def _get_owned_expense(db: Session, vehicle: Vehicle, expense_id: int) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.vehicle_id != vehicle.id:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


def _float(v: str | None) -> float:
    v = (v or "").strip().replace(",", ".")
    return float(v) if v else 0.0


def _category(value: str | None) -> ExpenseCategory:
    try:
        return ExpenseCategory((value or "").strip())
    except ValueError:
        return ExpenseCategory.other


@router.post("")
def add_expense(
    vehicle_id: int,
    category: str = Form("other"),
    title: str = Form(...),
    amount: str = Form("0"),
    spent_on: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    db.add(
        Expense(
            vehicle_id=vehicle.id,
            category=_category(category),
            title=title,
            amount=_float(amount),
            spent_on=date.fromisoformat(spent_on) if spent_on else date.today(),
            notes=notes or None,
        )
    )
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.get("/{expense_id}/edit")
def edit_expense_form(
    request: Request,
    vehicle_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    expense = _get_owned_expense(db, vehicle, expense_id)
    return render(request, "expenses/form.html", vehicle=vehicle, expense=expense)


@router.post("/{expense_id}/edit")
def update_expense(
    vehicle_id: int,
    expense_id: int,
    category: str = Form("other"),
    title: str = Form(...),
    amount: str = Form("0"),
    spent_on: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    expense = _get_owned_expense(db, vehicle, expense_id)
    expense.category = _category(category)
    expense.title = title
    expense.amount = _float(amount)
    expense.spent_on = date.fromisoformat(spent_on) if spent_on else date.today()
    expense.notes = notes or None
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)


@router.post("/{expense_id}/delete")
def delete_expense(
    vehicle_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    vehicle = _get_owned_vehicle(db, user, vehicle_id)
    expense = _get_owned_expense(db, vehicle, expense_id)
    db.delete(expense)
    db.commit()
    return RedirectResponse(f"/vehicles/{vehicle.id}", status_code=303)
