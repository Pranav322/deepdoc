from .common import *


def _stable_specialized_slug(base_slug: str, existing: set[str]) -> str:
    slug = base_slug
    suffix = 2
    while slug in existing:
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    return slug


def _auto_generate_endpoint_refs(
    plan: DocPlan,
    scan: RepoScan,
    include_endpoint_pages: bool = True,
) -> DocPlan:
    """Attach scanned endpoint details to grouped API-reference buckets.

    Historically this created one generated page per concrete route. That made
    large backend repos produce hundreds of thin pages. Runtime-discovered
    endpoints now feed endpoint-family pages, with bounded grouped fallback pages
    for endpoints that do not match an existing family.
    """
    import re as _re

    NOISE_PATHS = {
        "/health",
        "/healthz",
        "/ready",
        "/readyz",
        "/alive",
        "/ping",
        "/status",
        "/metrics",
        "/version",
        "/info",
        "/favicon.ico",
        "/robots.txt",
        "/sitemap.xml",
    }
    NOISE_SUFFIXES = (".svg", ".png", ".jpg", ".ico", ".css", ".js", ".map")
    ENDPOINT_DOMAIN_KEYWORDS: dict[str, set[str]] = {
        "auth": {
            "account",
            "applelogin",
            "auth",
            "blacklist",
            "block",
            "email",
            "facebooklogin",
            "forgetpassword",
            "googlelogin",
            "login",
            "logout",
            "otp",
            "password",
            "profile",
            "register",
            "resendotp",
            "resetpassword",
            "sendotp",
            "tfa",
            "token",
            "user",
            "verifyotp",
            "whitelist",
        },
        "orders": {
            "cancel",
            "checkout",
            "exchange",
            "hyperlocal",
            "order",
            "processorder",
            "purchase",
            "return",
            "survey",
            "thank",
            "undelivered",
        },
        "payments": {
            "cashback",
            "coupon",
            "discount",
            "giftvoucher",
            "pay",
            "payment",
            "refund",
            "tssmoney",
            "upi",
            "voucher",
            "wallet",
        },
        "products": {
            "artist",
            "catalog",
            "category",
            "feed",
            "gallery",
            "inventory",
            "listing",
            "price",
            "pricelist",
            "product",
            "rating",
            "search",
            "sitemap",
            "syncproduct",
            "tag",
            "theme",
            "variant",
            "wwe",
        },
        "cart": {
            "address",
            "cart",
            "checkout",
            "coupon",
            "giftvoucher",
            "wishlist",
        },
        "shipping": {
            "clickpost",
            "countries",
            "deliver",
            "delivery",
            "fulfillment",
            "location",
            "pincode",
            "reshipping",
            "ship",
            "shipment",
            "warehouse",
            "zone",
        },
        "support": {
            "callback",
            "contact",
            "feedback",
            "haptik",
            "notify",
            "notification",
            "nps",
            "question",
            "support",
            "ticket",
        },
        "loyalty": {
            "cashback",
            "climes",
            "exclusive",
            "loyalty",
            "point",
            "reward",
            "saving",
            "tss",
            "tssmoney",
        },
        "integrations": {
            "bittersweet",
            "bot",
            "cataloguemgmt",
            "convozen",
            "erp",
            "external",
            "firebase",
            "gmetri",
            "haptik",
            "omnichannel",
            "pos",
            "sync",
            "webhook",
        },
        "graphql": {"cmsgraphql", "graphql", "mutation", "query", "schema"},
        "cache": {
            "cache",
            "invalidate",
            "redis",
            "reset",
        },
    }

    endpoints = scan.published_api_endpoints
    if not include_endpoint_pages or not endpoints:
        return plan

    repo_profile = plan.classification.get("repo_profile", {})
    primary_type = repo_profile.get("primary_type", "other")
    restrict_endpoints = primary_type not in ("backend_service", "falcon_backend")

    def _resource_from_path(path: str) -> str:
        clean = _re.sub(r"^/(?:api/)?(?:v\d+/)?", "", path)
        parts_list = [
            p
            for p in clean.split("/")
            if p and not p.startswith(":") and not p.startswith("{")
        ]
        return parts_list[0] if parts_list else "general"

    def _resource_aliases(resource: str) -> set[str]:
        normalized = resource.lower().replace("_", "-")
        aliases = {normalized, normalized.replace("-", "_")}
        if normalized.endswith("s") and len(normalized) > 3:
            singular = normalized[:-1]
            aliases.update({singular, singular.replace("-", "_")})
        else:
            aliases.add(f"{normalized}s")
        return aliases

    def _bucket_tokens(bucket: DocBucket) -> set[str]:
        return _normalize_tokens(
            bucket.slug,
            bucket.title,
            bucket.description,
            " ".join(bucket.owned_symbols[:20]),
            " ".join(bucket.owned_files[:20]),
        )

    def _endpoint_tokens(ep: dict) -> set[str]:
        owned_files = endpoint_owned_files(ep)
        path_parts = _re.split(r"[^A-Za-z0-9_+-]+", ep.get("path", ""))
        return _normalize_tokens(
            ep.get("path", ""),
            ep.get("handler", ""),
            ep.get("name", ""),
            ep.get("summary", ""),
            " ".join(path_parts),
            " ".join(owned_files),
        )

    def _domain_labels(tokens: set[str]) -> set[str]:
        labels: set[str] = set()
        for label, keywords in ENDPOINT_DOMAIN_KEYWORDS.items():
            matched = False
            for token in tokens:
                for keyword in keywords:
                    if keyword == token:
                        matched = True
                    elif len(keyword) >= 4 and keyword in token:
                        matched = True
                    elif len(token) >= 4 and token in keyword:
                        matched = True
                    if matched:
                        break
                if matched:
                    break
            if matched:
                labels.add(label)
        return labels

    def _slugify(value: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "api"

    def _unique_slug(base_slug: str, existing_slugs: set[str]) -> str:
        slug = base_slug
        suffix = 2
        while slug in existing_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        existing_slugs.add(slug)
        return slug

    def _is_noise_endpoint(ep: dict) -> bool:
        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/unknown")
        handler = ep.get("handler", "")
        path_lower = path.lower()
        if path_lower in NOISE_PATHS:
            return True
        if any(path_lower.endswith(s) for s in NOISE_SUFFIXES):
            return True
        return path == "/" and method == "GET" and handler in ("root", "index", "home")

    endpoints = [ep for ep in endpoints if not _is_noise_endpoint(ep)]
    if not endpoints:
        return plan

    # Match against planned API-reference buckets, not only path-shaped
    # endpoint-family slugs. LLM plans often use semantic pages such as
    # user_auth_profile for /login, /logout, and /register.
    family_buckets = []
    for bucket in plan.buckets:
        hints = bucket.generation_hints or {}
        if hints.get("is_endpoint_ref") or hints.get("is_introduction_page"):
            continue
        section = (bucket.section or "").lower()
        if (
            hints.get("is_endpoint_family")
            or hints.get("include_endpoint_detail")
            or hints.get("prompt_style") == "endpoint"
            or section.startswith("api reference")
        ):
            family_buckets.append(bucket)

    bucket_profiles: dict[str, tuple[set[str], set[str]]] = {
        bucket.slug: (_bucket_tokens(bucket), _domain_labels(_bucket_tokens(bucket)))
        for bucket in family_buckets
    }

    def _best_endpoint_family(ep: dict) -> DocBucket | None:
        resource = _resource_from_path(ep.get("path", "/unknown"))
        resource_aliases = _resource_aliases(resource)
        ep_files = set(endpoint_owned_files(ep))
        ep_tokens = _endpoint_tokens(ep)
        ep_labels = _domain_labels(ep_tokens)

        best_bucket: DocBucket | None = None
        best_score = 0
        for bucket in family_buckets:
            bucket_tokens, bucket_labels = bucket_profiles[bucket.slug]
            score = 0
            score += len(ep_tokens & bucket_tokens) * 3
            score += len(ep_labels & bucket_labels) * 6
            if resource_aliases & bucket_tokens:
                score += 6
            if ep_files and ep_files & set(bucket.owned_files):
                score += 4
            if (bucket.generation_hints or {}).get("is_endpoint_family"):
                score += 1
            if score > best_score:
                best_score = score
                best_bucket = bucket

        return best_bucket if best_score >= 6 else None

    unmatched: list[dict] = []
    for ep in endpoints:
        if restrict_endpoints and not family_buckets:
            continue
        parent = _best_endpoint_family(ep)
        ep_files = endpoint_owned_files(ep)

        if parent:
            parent.owned_files = sorted({*parent.owned_files, *ep_files})
            parent.generation_hints["is_endpoint_family"] = True
            parent.generation_hints["include_endpoint_detail"] = True
            parent.generation_hints.setdefault("include_openapi", True)
            parent.generation_hints.setdefault("prompt_style", "endpoint")
        else:
            unmatched.append(ep)

    if unmatched:
        existing_slugs = {b.slug for b in plan.buckets}
        grouped: dict[str, list[dict]] = defaultdict(list)
        sparse: list[dict] = []
        fallback_page_count = 0

        for ep in unmatched:
            ep_labels = sorted(_domain_labels(_endpoint_tokens(ep)))
            if ep_labels:
                grouped[ep_labels[0]].append(ep)
                continue
            grouped[_resource_from_path(ep.get("path", "/unknown"))].append(ep)

        for group_key, group_eps in list(grouped.items()):
            if len(group_eps) < 3 and group_key not in ENDPOINT_DOMAIN_KEYWORDS:
                sparse.extend(group_eps)
                del grouped[group_key]

        if sparse:
            grouped["supporting"] = sparse

        for group_key, group_eps in sorted(grouped.items()):
            display = group_key.replace("_", " ").replace("-", " ").title()
            base_slug = (
                "additional-api-endpoints"
                if group_key == "supporting"
                else f"{_slugify(group_key)}-api-endpoints"
            )
            slug = _unique_slug(base_slug, existing_slugs)
            ep_files = sorted(
                {f for ep in group_eps for f in endpoint_owned_files(ep)}
            )
            handlers = sorted(
                {ep.get("handler", "") for ep in group_eps if ep.get("handler")}
            )
            plan.buckets.append(
                DocBucket(
                    bucket_type="endpoint-family",
                    title=(
                        "Additional API Endpoints"
                        if group_key == "supporting"
                        else f"{display} API Endpoints"
                    ),
                    slug=slug,
                    section="API Reference",
                    description=(
                        "Grouped API reference for scanned runtime endpoints that did "
                        "not match a planned endpoint family "
                        f"({len(group_eps)} endpoints)."
                    ),
                    owned_files=ep_files,
                    owned_symbols=handlers[:50],
                    required_sections=[
                        "route_overview",
                        "auth_validation",
                        "execution_flow",
                        "downstream_calls",
                        "state_changes",
                        "response_errors",
                        "diagrams",
                    ],
                    generation_hints={
                        "is_endpoint_family": True,
                        "include_endpoint_detail": True,
                        "include_openapi": True,
                        "prompt_style": "endpoint",
                        "icon": "globe-alt",
                    },
                    priority=24,
                )
            )
            fallback_page_count += 1
            plan.nav_structure.setdefault("API Reference", []).append(slug)
    else:
        fallback_page_count = 0

    attached = len(endpoints) - len(unmatched)
    if attached or unmatched:
        console.print(
            "[green]✓ Grouped "
            f"{attached} endpoint(s) into family pages"
            f"{f' and {len(unmatched)} into {fallback_page_count} grouped fallback page(s)' if unmatched else ''}"
            "[/green]"
        )

    return plan
