from django.contrib.auth import (
    get_user_model,
    update_session_auth_hash,
)
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from ..models import (
    Profile,
    Workspace,
)
from .. import services as s
from ..presentation import (
    user_data,
    organization_data,
)


from core.views.auth import mutation

ACCOUNT_LANGUAGES = {"pl", "en"}
ACCOUNT_ZONES = {
    "Europe/Warsaw",
    "Europe/Berlin",
    "Europe/Prague",
    "Europe/London",
    "UTC",
}
ACCOUNT_PAGES = {
    "dashboard",
    "orders",
    "production",
    "shipping",
    "stock",
    "catalog",
    "customers",
    "users",
    "admin",
}

@api_view(["POST"])
@mutation
def account_update(request):
    data = request.data
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValidationError("Podaj imię lub nazwę.")
    email = str(data.get("email", "")).strip()
    if email:
        try:
            validate_email(email)
        except DjangoValidationError:
            raise ValidationError("Podaj poprawny e-mail.")
    language = str(data.get("language", "pl"))
    zone = str(data.get("timezone", "Europe/Warsaw"))
    start_page = str(data.get("start_page", "dashboard"))
    appearance = str(data.get("appearance", "light"))
    if (
        language not in ACCOUNT_LANGUAGES
        or zone not in ACCOUNT_ZONES
        or start_page not in ACCOUNT_PAGES
        or appearance not in {"light", "dark"}
    ):
        raise ValidationError(
            "Wybierz język, strefę czasową, ekran startowy i wygląd z listy."
        )
    user = request.user
    user.first_name = name[:150]
    user.email = email
    user.save(update_fields=["first_name", "email"])
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.phone = str(data.get("phone", ""))[:40]
    profile.street = str(data.get("street", ""))[:180]
    profile.postal_code = str(data.get("postal_code", ""))[:20]
    profile.city = str(data.get("city", ""))[:80]
    profile.country = str(data.get("country", ""))[:80]
    profile.language = language
    profile.timezone = zone
    profile.start_page = start_page
    profile.appearance = appearance
    profile.save()
    return user_data(user)



@api_view(["POST"])
@mutation
def account_password(request):
    user = request.user
    if not user.check_password(str(request.data.get("current_password", ""))):
        raise ValidationError("Obecne hasło jest nieprawidłowe.")
    password = str(request.data.get("password", ""))
    if password != str(request.data.get("password_repeat", "")):
        raise ValidationError("Nowe hasła nie są takie same.")
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages)
    user.set_password(password)
    user.save(update_fields=["password"])
    update_session_auth_hash(getattr(request, "_request", request), user)
    return {"ok": True}



@api_view(["GET", "POST"])
def users(request):
    s.permit(request.user, "admin")
    if request.method == "GET":
        return Response(
            [user_data(u) for u in get_user_model().objects.order_by("username")]
        )
    return save_user(request)



@mutation
def save_user(request):
    data = request.data
    user = (
        get_object_or_404(get_user_model(), pk=data["id"])
        if data.get("id")
        else get_user_model()()
    )
    is_new = user.pk is None
    if user.is_superuser and not request.user.is_superuser:
        raise ValidationError("Tylko superadministrator może zmieniać to konto.")
    if user.pk == request.user.pk and (
        data.get("active") is False or "admin" not in data.get("roles", [])
    ):
        raise ValidationError("Nie możesz odebrać sobie dostępu do administracji.")
    user.username = str(data.get("username", user.username)).strip()[:150]
    if not user.username:
        raise ValidationError("Podaj login.")
    user.first_name = str(data.get("name", user.first_name))[:150]
    user.is_active = data.get("active", True)
    selected = data.get("roles", [])
    if not selected or set(selected) - set(s.ROLES):
        raise ValidationError("Wybierz poprawne role.")
    password = data.get("password")
    if password:
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        user.set_password(password)
    elif not user.pk:
        raise ValidationError("Podaj hasło nowego użytkownika.")
    user.save()
    if is_new:
        profile, _created = Profile.objects.get_or_create(user=user)
        profile.language = s.organization().default_language
        profile.save(update_fields=["language"])
    user.groups.set([Group.objects.get_or_create(name=r)[0] for r in selected])
    s.event(
        None,
        request.user,
        "Zmieniono użytkownika",
        id=user.pk,
        roles=selected,
        active=user.is_active,
    )
    return {"id": user.pk}



@api_view(["POST"])
@mutation
def organization_update(request):
    s.permit(request.user, "admin")
    name = str(request.data.get("name", "")).strip()
    if not name:
        raise ValidationError("Podaj nazwę organizacji.")
    language = str(request.data.get("default_language", "pl"))
    theme = str(request.data.get("theme", "plum"))
    if language not in ACCOUNT_LANGUAGES or theme not in s.THEMES:
        raise ValidationError("Wybierz język i motyw z listy.")
    org = s.organization()
    org.name = name[:80]
    org.default_language = language
    org.theme = theme
    org.save(update_fields=["name", "default_language", "theme"])
    s.event(None, request.user, "Zmieniono ustawienia organizacji", name=org.name)
    return organization_data(org)



@api_view(["POST"])
@mutation
def workspace_save(request):
    s.permit(request.user, "admin")
    data = request.data
    space = (
        get_object_or_404(Workspace, pk=data["id"])
        if data.get("id")
        else Workspace(primary=False, active=True)
    )
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValidationError("Podaj nazwę przestrzeni produkcyjnej.")
    if Workspace.objects.exclude(pk=space.pk).filter(name__iexact=name).exists():
        raise ValidationError("Taka przestrzeń już istnieje.")
    space.name = name[:80]
    if space.pk and "active" in data:
        active = bool(data.get("active"))
        if space.primary and not active:
            raise ValidationError("Domyślnej przestrzeni nie można wyłączyć.")
        if (
            not active
            and not Workspace.objects.exclude(pk=space.pk).filter(active=True).exists()
        ):
            raise ValidationError("Zostaw przynajmniej jedną aktywną przestrzeń.")
        if space.active and not active:
            Profile.objects.filter(current_workspace=space).update(current_workspace=None)
        space.active = active
    space.save()
    s.event(
        None,
        request.user,
        "Zapisano przestrzeń produkcyjną",
        id=space.pk,
        name=space.name,
        active=space.active,
    )
    return {
        "id": space.pk,
        "name": space.name,
        "active": space.active,
        "primary": space.primary,
    }



@api_view(["POST"])
@mutation
def workspace_select(request):
    space = get_object_or_404(Workspace, pk=request.data.get("id"), active=True)
    profile, _created = Profile.objects.get_or_create(user=request.user)
    profile.current_workspace = space
    profile.save(update_fields=["current_workspace"])
    return {"id": space.pk}



