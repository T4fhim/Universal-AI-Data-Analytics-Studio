# File: apps/api/uadas_api/accounts/security.py
"""Request-level authentication and the organization gate every tenant route uses.

Two things live here because every router needs both and they must not be re-invented:

* :data:`session_auth` -- Django Ninja's session authentication **with CSRF enforcement**.
  Ninja exempts every view from Django's CSRF middleware and relies on the auth class to do
  the check, so a route without it is both unauthenticated and CSRF-free; ``api.build_api``
  therefore applies it to the whole API and the single public route (liveness) opts out.
* :func:`require_membership` -- organization selection is *stateless and path-based*
  (``/api/organizations/{org_id}/...``): there is no "current organization" in the session to
  get stale or be forged. Each request names the organization and this function decides what
  the caller may do there. Outcomes: not signed in -> 401; signed in but not a member -> 404
  (the same answer as for an organization that does not exist, so ids cannot be probed);
  a member below ``min_role`` -> 403; otherwise the caller's :class:`Membership`.
"""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja.errors import HttpError
from ninja.security import SessionAuth

from uadas_api.accounts.models import Membership, Role, User
from uadas_api.accounts.permissions import role_at_least

session_auth = SessionAuth(csrf=True)


def require_membership(
    request: HttpRequest, org_id: uuid.UUID, min_role: Role = Role.VIEWER
) -> Membership:
    """Return the caller's membership in ``org_id``, or raise the right ``HttpError``.

    ``min_role`` is the lowest role allowed (see ``accounts/permissions.py`` for the
    order and the capability matrix). The returned membership has ``organization`` and
    ``user`` loaded.
    """
    user = request.user
    if not isinstance(user, User) or not user.is_active:
        raise HttpError(401, "Authentication required.")
    membership = (
        Membership.objects.select_related("organization", "user")
        .filter(user=user, organization_id=org_id)
        .first()
    )
    if membership is None:
        # Deliberately the same body as for an organization that does not exist.
        raise HttpError(404, "Not found.")
    if not role_at_least(membership.role, min_role):
        raise HttpError(403, "Your role does not allow this.")
    return membership
