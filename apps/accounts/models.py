"""Global (non-tenant) user model. Users join organizations through tenancy.Membership."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError(_("An email address is required."))
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email = models.EmailField(_("email address"), unique=True)
    name = models.CharField(_("name"), max_length=150, blank=True)
    locale = models.CharField(_("language"), max_length=10, default="en")
    timezone = models.CharField(_("time zone"), max_length=64, default="UTC")
    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(_("staff status"), default=False)
    date_joined = models.DateTimeField(_("date joined"), default=dj_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ("email",)

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        return self.name or self.email

    def get_short_name(self) -> str:
        return (self.name or self.email).split(" ")[0]
