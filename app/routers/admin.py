"""Administrator user management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.security import hash_password, require_admin
from app.templating import render

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
def list_users(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = db.query(User).order_by(User.username).all()
    return render(request, "admin/users.html", users=users)


@router.post("/users")
def create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_repeat: str | None = Form(None),
    is_admin: str = Form(""),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if len(password) < settings.min_password_length:
        users = db.query(User).order_by(User.username).all()
        return render(
            request,
            "admin/users.html",
            users=users,
            error="auth.password.too_short",
            min_password_length=settings.min_password_length,
        )
    # Validated when the form sends the confirmation field (the UI always does).
    if password_repeat is not None and password != password_repeat:
        users = db.query(User).order_by(User.username).all()
        return render(
            request, "admin/users.html", users=users, error="account.password.mismatch"
        )

    exists = (
        db.query(User)
        .filter((User.email == email) | (User.username == username))
        .first()
    )
    if exists:
        users = db.query(User).order_by(User.username).all()
        return render(request, "admin/users.html", users=users, error="auth.register.taken")

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        is_admin=bool(is_admin),
        locale=settings.default_locale,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/users/{user_id}/edit")
def edit_user_form(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return render(request, "admin/user_form.html", target=target)


@router.post("/users/{user_id}/edit")
def edit_user(
    user_id: int,
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    password_repeat: str | None = Form(None),
    is_admin: str = Form(""),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    def form_error(error: str):
        return render(
            request,
            "admin/user_form.html",
            target=target,
            error=error,
            min_password_length=settings.min_password_length,
        )

    # Password is optional here: empty means "keep the current one".
    if password and len(password) < settings.min_password_length:
        return form_error("auth.password.too_short")
    # Validated when the form sends the confirmation field (the UI always does).
    # Also catches a filled confirmation with an empty password field.
    if password_repeat is not None and password != password_repeat:
        return form_error("account.password.mismatch")

    taken = (
        db.query(User)
        .filter(
            User.id != target.id,
            (User.email == email) | (User.username == username),
        )
        .first()
    )
    if taken:
        return form_error("auth.register.taken")

    target.username = username
    target.email = email
    if target.id != admin.id:  # never demote yourself
        target.is_admin = bool(is_admin)
    if password:
        target.hashed_password = hash_password(password)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle-active")
def toggle_active(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id != admin.id:  # never lock yourself out
        user.is_active = not user.is_active
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete yourself")
    db.delete(user)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)
