# Authentication and Permissions

## 1. Principal and context

```python
@dataclass(frozen=True)
class Principal:
    provider: str               # "dev" | "easyauth-aad" | "oidc:<iss>" | "host" | "token"
    subject: str                # oid / sub / token id
    tenant_id: str | None
    email: str | None
    name: str | None
    roles: tuple[str, ...]      # IdP roles/app roles (e.g., "Momentum.Admin")
    raw_claims: Mapping[str, Any]

@dataclass(frozen=True)
class Ctx:
    user: User                  # resolved Momentum user (may be an agent user)
    workspace_id: UUID
    acting_for: User | None     # agent acting on behalf of a user (chat/command)
    request_id: str
    dry_run: bool = False
    via: str = "ui"             # created_via value for writes
```

**Identity comes only from the server-side auth provider.** There are no `?actingAs=` query parameters or client-supplied user ids (a change from the Care Cockpit pattern).

## 2. Auth providers (`MOMENTUM_AUTH_MODE`)

```python
class AuthProvider(Protocol):
    async def authenticate(self, request: Request) -> Principal | None: ...
    def login_url(self, return_to: str) -> str: ...
    def logout_url(self, return_to: str) -> str: ...
```

| Mode | Environment | How it works | Guards |
|---|---|---|---|
| `dev` | Local | `/dev/login` page lists active seeded users; sets a signed `momentum_dev_session` cookie (itsdangerous, `MOMENTUM_SECRET_KEY`) | Refuses to start if `MOMENTUM_ENV=production` |
| `easyauth-sim` | Local | Dev middleware picks the user from the dev session and **injects realistic `X-MS-CLIENT-PRINCIPAL*` headers**, then the real `easyauth` provider parses them | Same as dev |
| `easyauth` | Azure App Service | Decodes the base64 `X-MS-CLIENT-PRINCIPAL` JSON: claims `http://schemas.microsoft.com/identity/claims/objectidentifier` (oid), `http://schemas.microsoft.com/identity/claims/tenantid` (tid), `preferred_username`/`email`/`upn`, `name`, and role claims (`roles` or the `role_typ` claim type). Login is `/.auth/login/aad?post_login_redirect_uri=…`, logout is `/.auth/logout?post_logout_redirect_uri=…`. | Refuses to start unless `WEBSITE_SITE_NAME` is present (App Service) or `MOMENTUM_EASYAUTH_TRUST_HEADERS=true` is set explicitly |
| `oidc` | Non-Azure hosting | Authlib code flow; own session cookie | Requires issuer, client id/secret |
| `host` | Embedded in another app | The host passes a callable `resolve_principal(request) -> Principal \| None` to `mount_momentum()` | See `embedding-and-portability.md` |
| API tokens | All | `Authorization: Bearer mtm_…` checked before the provider on token-enabled paths (`/mcp`, `/api/v1/*` when `MOMENTUM_API_TOKENS_ENABLED`) | Hashed at rest, scoped, expirable |

### Easy Auth claim-mapping settings
`MOMENTUM_EASYAUTH_EMAIL_CLAIMS` (default `preferred_username,email,upn,http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`), `MOMENTUM_ADMIN_ROLE` (default `Momentum.Admin`), `MOMENTUM_ALLOWED_TENANT_IDS`, `MOMENTUM_ALLOWED_EMAIL_DOMAINS`.

### Frontend flow
1. The SPA calls `GET /api/v1/me` on boot.
2. `200` → store the user. `401` → the response carries `login_url` in problem+json → `window.location.assign(login_url)`.
3. Logout → `GET /api/v1/auth/logout-url` → navigate.
4. On any later 401 (expired session), show a "Session expired, sign in again" banner with a button (don't lose unsaved text; drafts are kept in localStorage).

## 3. Identity resolution (`auth/identity.py`)

```
resolve_user(principal):
  1. identity = user_identities[(provider, tenant_id, subject)] → user  (update last_login_at)
  2. else if principal.email and MOMENTUM_IDENTITY_LINK_BY_EMAIL:
        user = users[(workspace, lower(email))]
        if user: create identity link → user          # lift-and-shift / tenant change
  3. else if auto-provisioning allowed (tenant/domain allow-listed):
        create user(role = admin if email in BOOTSTRAP_ADMIN_EMAILS or ADMIN_ROLE in roles else member)
        create identity link
  4. else → 403 "not_invited"
  5. If user.status == disabled → 403 "account_disabled"
  6. If ADMIN_ROLE in principal.roles and MOMENTUM_SYNC_ADMIN_ROLE → ensure role=admin
```

## 4. Workspace roles

| Capability | Admin | Member | Guest (later) |
|---|---|---|---|
| See all `team`-privacy projects of teams they belong to | ✓ (all teams) | ✓ | Only explicitly shared projects |
| Create teams | ✓ | ✓ | ✗ |
| Create projects | ✓ | ✓ (in their teams) | ✗ |
| Manage users/roles, AI settings, budgets, integrations | ✓ | ✗ | ✗ |
| Create/edit agents | ✓ | Personal/project agents (Phase 5 setting) | ✗ |
| See private projects they aren't a member of | ✗ (admins can see *that it exists* in admin settings, not content) | ✗ | ✗ |

## 4a. Team rules (implemented in `momentum/domain/access.py`)

| Action | Admin | Team lead | Team member | Not a member |
|---|---|---|---|---|
| See team + members | ✓ | ✓ | ✓ | ✗ (404) |
| Create a team | ✓ | ✓ | ✓ | ✓ (members of the workspace) |
| Rename / describe / delete team | ✓ | ✓ | ✗ (403) | ✗ (404) |
| Add members, change roles | ✓ | ✓ | ✗ | ✗ |
| Remove a member | ✓ | ✓ | only themselves (leave) | ✗ |
| Last lead | Can't be demoted or removed; the team always keeps at least one lead (409 `last_lead`) | | | |

## 5. Project roles

| Action | Project admin | Editor | Commenter | Viewer |
|---|---|---|---|---|
| View project and tasks | ✓ | ✓ | ✓ | ✓ |
| Comment, react, follow | ✓ | ✓ | ✓ | ✗ |
| Create/edit/complete/move tasks | ✓ | ✓ | ✗ | ✗ |
| Manage sections, fields, views | ✓ | ✓ | ✗ | ✗ |
| Manage rules, forms, templates | ✓ | ✓ (setting) | ✗ | ✗ |
| Manage members, privacy, archive/delete project | ✓ | ✗ | ✗ | ✗ |

Team members get **editor** by default on `team`-privacy projects of their team, unless a per-project role says otherwise. Workspace admins get **admin** on `team`-privacy projects. **Private** projects are visible only to explicit project members, admins included. Projects of a deleted team are hidden. Editors may rename/recolor and change the default view; privacy, archive and delete need project **admin**. Implemented in `momentum/domain/access.py` (`project_role`, `visible_projects_clause`, `get_visible_project`). Sharing: project admins add people with a role (explicit roles override the team default, in both directions); every project keeps at least one explicit admin (409 `last_admin`); anyone can leave a project they were explicitly added to.

## 6. Task visibility

A user can see task T if **any** of these hold:
1. T is in a project P the user can view, or
2. the user is T's assignee, creator, or a follower, or
3. T is a subtask of a task the user can see (subtasks inherit parent visibility).

This is implemented once in `permissions.visible_tasks_clause(ctx)` (a SQL expression) and reused by lists, search, AI retrieval, notifications, and exports.

## 7. `can()`

```python
def can(ctx: Ctx, action: Action, resource: Resource) -> bool
def require(ctx: Ctx, action: Action, resource: Resource) -> None   # raises Forbidden/NotFound
```

Actions are string constants (`"project.view"`, `"project.edit"`, `"project.manage"`, `"task.view"`, `"task.edit"`, `"task.comment"`, `"workspace.admin"`, `"agent.manage"`, …). Unit tests cover the full matrix above with factories. **Any change to this file needs human approval** (CLAUDE.md §6).

## 8. Agents and permissions

- **Acting for a user** (chat, ⌘K, inline AI): `ctx.user = the human`, `ctx.via="ai"`. The AI can do exactly what the user can.
- **Acting as itself** (scheduled/event agents): `ctx.user = agent user`. Visibility = the agent's `scope` (projects/teams) ∩ what the scope grants. Agents are project members with a role (default `editor` for write agents, `commenter` for suggest-only agents).
- Even with permission, AI writes follow the autonomy and risk policy (`ai/ai-architecture.md` §4).
