from .common import *

def discover_database_schema(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    file_tree: dict[str, list[str]],
    repo_root: Path,
) -> DatabaseScan:
    """Detect ORM model files, migrations, and schema definitions.

    Supports: Django, SQLAlchemy, Prisma, TypeORM, Sequelize, Eloquent,
    Mongoose, GORM, Alembic, and generic model patterns.
    """
    result = DatabaseScan()

    # ORM detection patterns (searched in file content)
    ORM_PATTERNS: dict[str, list[re.Pattern]] = {
        "django": [
            re.compile(r"from django\.db import models"),
            re.compile(r"models\.Model\b"),
            re.compile(r"class \w+\(models\.Model\)"),
        ],
        "sqlalchemy": [
            re.compile(r"from sqlalchemy"),
            re.compile(r"declarative_base\(\)"),
            re.compile(r"class \w+\(.*Base\)"),
            re.compile(r"Column\("),
            re.compile(r"relationship\("),
        ],
        "prisma": [
            re.compile(r"model\s+\w+\s*\{"),
            re.compile(r"datasource\s+\w+\s*\{"),
        ],
        "typeorm": [
            re.compile(r"@Entity\s*\("),
            re.compile(r"@Column\s*\("),
            re.compile(r"@PrimaryGeneratedColumn"),
            re.compile(r"@ManyToOne|@OneToMany|@ManyToMany|@OneToOne"),
        ],
        "sequelize": [
            re.compile(r"sequelize\.define\("),
            re.compile(r"DataTypes\.\w+"),
            re.compile(r"Model\.init\("),
            re.compile(r"\.belongsTo\(|\.hasMany\(|\.hasOne\(|\.belongsToMany\("),
        ],
        "eloquent": [
            re.compile(r"extends Model\b"),
            re.compile(r"\\$fillable|\\$guarded|\\$casts"),
            re.compile(r"Illuminate\\Database"),
        ],
        "mongoose": [
            re.compile(r"mongoose\.Schema\("),
            re.compile(r"new Schema\("),
            re.compile(r"mongoose\.model\("),
        ],
        "gorm": [
            re.compile(r"gorm\.Model"),
            re.compile(r"gorm\.DB"),
            re.compile(r"db\.AutoMigrate"),
        ],
        "knex": [
            re.compile(r"knex\.schema\.(?:createTable|alterTable|table)\s*\("),
            re.compile(r"\bknex\s*\(\s*['\"][A-Za-z0-9_.-]+['\"]\s*\)"),
            re.compile(
                r"\btable\.(?:string|integer|bigInteger|uuid|boolean|timestamp|json|enu)\s*\("
            ),
        ],
    }

    # Migration directory/file patterns
    MIGRATION_PATTERNS = [
        "migration",
        "migrations",
        "alembic",
        "migrate",
        "db/migrate",
        "database/migrations",
    ]
    MIGRATION_FILE_PATTERNS = [
        re.compile(r"^\d{4}_"),  # Django: 0001_initial.py
        re.compile(r"^\d{14}"),  # Alembic/Rails timestamps
        re.compile(r"V\d+__"),  # Flyway
        re.compile(r"\.migration\.\w+$"),
    ]

    # Schema file patterns
    SCHEMA_PATTERNS = [
        "prisma/schema.prisma",
        "schema.prisma",
        "schema.graphql",
        "schema.gql",
        "schema.sql",
        "init.sql",
        "create_tables.sql",
        "dbdiagram",
        "erd",
    ]

    # Phase 1: Detect model files from parsed content
    orm_counts: dict[str, int] = defaultdict(int)

    for file_path, content in file_contents.items():
        if not content:
            continue

        path_lower = file_path.lower()
        parsed = parsed_files.get(file_path)

        # Skip test/migration files for model detection
        if any(p in path_lower for p in ("test", "spec", "fixture", "factory", "seed")):
            continue

        # Check migrations
        is_migration = False
        for mp in MIGRATION_PATTERNS:
            if mp in path_lower:
                result.migration_files.append(file_path)
                is_migration = True
                break
        if not is_migration:
            fname = file_path.split("/")[-1]
            for mp in MIGRATION_FILE_PATTERNS:
                if mp.search(fname):
                    result.migration_files.append(file_path)
                    is_migration = True
                    break
        if is_migration:
            continue

        # Check schema files
        for sp in SCHEMA_PATTERNS:
            if sp.lower() in path_lower:
                result.schema_files.append(file_path)

        # Check ORM patterns
        best_orm = ""
        best_score = 0
        for orm_name, patterns in ORM_PATTERNS.items():
            score = sum(1 for p in patterns if p.search(content))
            if score > best_score:
                best_score = score
                best_orm = orm_name
            if score > 0:
                orm_counts[orm_name] += score

        # Only count as model file if we got >= 2 pattern matches (reduces false positives)
        if best_score >= 2 or (
            best_score >= 1
            and any(kw in path_lower for kw in ("model", "schema", "entity"))
        ):
            # Extract model/class names
            model_names: list[str] = []
            if parsed and parsed.symbols:
                for s in parsed.symbols:
                    if s.kind == "class":
                        model_names.append(s.name)

            # For Prisma/SQL schema, extract model names from content
            if best_orm == "prisma":
                model_names = re.findall(r"model\s+(\w+)\s*\{", content)

            result.model_files.append(
                ModelFileInfo(
                    file_path=file_path,
                    orm_framework=best_orm,
                    model_names=model_names,
                    is_migration=False,
                )
            )
            result.total_models += len(model_names)

    # Phase 2: Determine primary ORM
    if orm_counts:
        result.orm_framework = max(orm_counts, key=lambda k: orm_counts[k])
        result.orm_frameworks = sorted(orm_counts.keys())

    result.graphql_interfaces = discover_graphql_interfaces(parsed_files, file_contents)
    result.knex_artifacts = discover_knex_artifacts(parsed_files, file_contents)
    if result.knex_artifacts and "knex" not in result.orm_frameworks:
        result.orm_frameworks.append("knex")
        if not result.orm_framework:
            result.orm_framework = "knex"
    result.groups = build_database_groups(result, parsed_files)

    # Deduplicate
    result.migration_files = sorted(set(result.migration_files))
    result.schema_files = sorted(set(result.schema_files))

    if result.model_files or result.migration_files or result.schema_files:
        console.print(
            f"  [dim]Database: {len(result.model_files)} model file(s), "
            f"{result.total_models} model(s), "
            f"{len(result.migration_files)} migration(s), "
            f"ORM: {result.orm_framework or 'unknown'}[/dim]"
        )

    return result


def discover_graphql_interfaces(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
) -> list[GraphQLInterface]:
    """Detect GraphQL schema surfaces, primarily Graphene-style Python code."""
    interfaces: list[GraphQLInterface] = []
    object_pattern = re.compile(
        r"class\s+(\w+)\((?:graphene\.)?(ObjectType|Mutation)\)\s*:"
    )
    schema_pattern = re.compile(r"(\w+)\s*=\s*graphene\.Schema\s*\(([^)]*)\)")
    field_pattern = re.compile(
        r"^\s*(\w+)\s*=\s*graphene\.(Field|List|String|Int|Boolean|ID|Float)\b",
        re.MULTILINE,
    )
    resolver_pattern = re.compile(r"def\s+(resolve_\w+|mutate)\s*\(")

    for file_path, content in file_contents.items():
        if not content:
            continue
        lowered = content.lower()
        if "graphene" not in lowered and "graphql" not in lowered:
            continue

        for match in object_pattern.finditer(content):
            name = match.group(1)
            kind = match.group(2).lower()
            class_body = content[match.start() : match.start() + 4000]
            fields = sorted(set(field_pattern.findall(class_body)))
            resolvers = sorted(set(resolver_pattern.findall(class_body)))
            interfaces.append(
                GraphQLInterface(
                    name=name,
                    file_path=file_path,
                    kind="mutation" if kind == "mutation" else "object_type",
                    fields=[item[0] for item in fields[:20]],
                    related_types=resolvers[:20],
                )
            )

        for match in schema_pattern.finditer(content):
            name = match.group(1)
            related = []
            for token in ("query", "mutation", "subscription"):
                value_match = re.search(
                    rf"{token}\s*=\s*([A-Za-z_][A-Za-z0-9_]*)", match.group(2)
                )
                if value_match:
                    related.append(f"{token}:{value_match.group(1)}")
            interfaces.append(
                GraphQLInterface(
                    name=name,
                    file_path=file_path,
                    kind="schema",
                    related_types=related,
                )
            )

    deduped: dict[tuple[str, str, str], GraphQLInterface] = {}
    for item in interfaces:
        deduped[(item.file_path, item.name, item.kind)] = item
    return list(deduped.values())


def discover_knex_artifacts(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
) -> list[KnexArtifact]:
    """Detect Knex schema and query-builder usage."""
    artifacts: list[KnexArtifact] = []
    schema_call = re.compile(
        r"knex\.schema\.(createTable|alterTable|table)\s*\(\s*['\"]([A-Za-z0-9_.-]+)['\"]"
    )
    table_column = re.compile(
        r"table\.(string|integer|bigInteger|uuid|boolean|timestamp|json|enu)\s*\(\s*['\"]([A-Za-z0-9_.-]+)['\"]"
    )
    fk_pattern = re.compile(r"\.references\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
    query_pattern = re.compile(
        r"\bknex\s*\(\s*['\"]([A-Za-z0-9_.-]+)['\"]\s*\)\s*(\.[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?){0,6}"
    )

    for file_path, content in file_contents.items():
        if "knex" not in content:
            continue

        for match in schema_call.finditer(content):
            snippet = content[match.start() : match.start() + 3000]
            artifacts.append(
                KnexArtifact(
                    file_path=file_path,
                    artifact_type="schema",
                    table_name=match.group(2),
                    columns=[col[1] for col in table_column.findall(snippet)[:30]],
                    foreign_keys=fk_pattern.findall(snippet)[:20],
                )
            )

        for match in query_pattern.finditer(content):
            table_name = match.group(1)
            chain = match.group(0)
            artifacts.append(
                KnexArtifact(
                    file_path=file_path,
                    artifact_type="query",
                    table_name=table_name,
                    query_patterns=[chain[:200]],
                )
            )

    deduped: dict[tuple[str, str, str, str], KnexArtifact] = {}
    for item in artifacts:
        key = (
            item.file_path,
            item.artifact_type,
            item.table_name,
            "|".join(item.query_patterns[:1]),
        )
        if key not in deduped:
            deduped[key] = item
    return list(deduped.values())


def build_database_groups(
    db_scan: DatabaseScan,
    parsed_files: dict[str, ParsedFile],
) -> list[DatabaseGroup]:
    """Group model/schema files into deterministic database documentation buckets."""
    grouped: dict[str, DatabaseGroup] = {}
    model_lookup = {mf.file_path: mf for mf in db_scan.model_files}

    for file_path in sorted({*model_lookup.keys(), *db_scan.schema_files}):
        parts = Path(file_path).parts
        group_key = _database_group_key(parts)
        label = group_key.replace("-", " ").replace("_", " ").title()
        group = grouped.setdefault(
            group_key,
            DatabaseGroup(key=group_key, label=label),
        )
        group.file_paths.append(file_path)
        model_info = model_lookup.get(file_path)
        if model_info:
            group.model_names.extend(model_info.model_names)
            if model_info.orm_framework:
                group.orm_frameworks.append(model_info.orm_framework)
        elif file_path in db_scan.schema_files:
            group.orm_frameworks.extend(db_scan.orm_frameworks[:1])

    # Add cross-group references using parsed imports
    path_to_group = {
        file_path: group.key
        for group in grouped.values()
        for file_path in group.file_paths
    }
    import_lookup = _build_import_lookup(set(path_to_group.keys()))
    for group in grouped.values():
        external_refs: set[str] = set()
        for file_path in group.file_paths:
            parsed = parsed_files.get(file_path)
            if not parsed:
                continue
            for imported in _resolve_imports_to_files(
                parsed.imports, file_path, import_lookup
            ):
                imported_group = path_to_group.get(imported)
                if imported_group and imported_group != group.key:
                    external_refs.add(imported_group)
        group.model_names = sorted(set(group.model_names))
        group.orm_frameworks = sorted(set(group.orm_frameworks))
        group.external_refs = sorted(external_refs)

    return sorted(grouped.values(), key=lambda item: item.key)


def _database_group_key(parts: tuple[str, ...]) -> str:
    lowered = [part.lower() for part in parts]
    if "models" in lowered:
        idx = lowered.index("models")
        if idx > 0:
            return lowered[idx - 1]
        if idx + 1 < len(lowered):
            return lowered[idx + 1]
    for anchor in (
        "orderrefund",
        "orderreturnstatus",
        "graphql",
        "schema",
        "schemas",
        "entities",
    ):
        if anchor in lowered:
            return anchor
    if len(lowered) >= 3 and lowered[0] in {"src", "app", "api", "orderreverse"}:
        return lowered[1]
    if len(lowered) >= 2:
        return lowered[-2]
    return lowered[0] if lowered else "database"


from .utils import _build_import_lookup, _resolve_imports_to_files
