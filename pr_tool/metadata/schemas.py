"""Per-repository metadata schemas."""

from metadata import choices as c
from metadata.schema import FieldSpec, MetadataSchema

TITLE_MAX_LENGTH = 40
DESCRIPTION_MAX_LENGTH = 100
LONG_DESCRIPTION_MAX_LENGTH = None

_SHARED_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        'title', 'Project title', 'text',
        max_length=TITLE_MAX_LENGTH,
        cli_flag='--title',
        cli_help=f'The title of the project; max {TITLE_MAX_LENGTH} characters.',
    ),
    FieldSpec(
        'description', 'Project description', 'text',
        max_length=DESCRIPTION_MAX_LENGTH,
        cli_flag='--description',
        cli_help=f'Short description; max {DESCRIPTION_MAX_LENGTH} characters.',
    ),
    FieldSpec(
        'long_description', 'Long description', 'long_text',
        max_length=LONG_DESCRIPTION_MAX_LENGTH,
    ),
    FieldSpec(
        'sensors', 'Sensor', 'multi_choice',
        choices=c.SENSORS,
        cli_flag='--sensor',
        cli_help='Target sensor(s). Pass --sensor multiple times for more than one.',
        cli_choices=c.SENSORS,
        cli_action='append',
    ),
    FieldSpec('domain', 'Domain', 'multi_choice', choices=c.DOMAIN),
    FieldSpec(
        'application', 'Application', 'multi_choice',
        choices=c.APPLICATION,
        allow_custom=False,
    ),
    FieldSpec('use_case', 'Use case', 'multi_choice', choices=c.USE_CASE),
    FieldSpec('kit', 'Kit', 'multi_choice', choices=c.KIT),
    FieldSpec('device', 'Device', 'multi_choice', choices=c.DEVICE),
    FieldSpec(
        'type', 'Project type', 'multi_choice',
        choices=c.PROJECT_TYPE,
        allow_custom=False,
    ),
    FieldSpec(
        'workflow', 'Workflow', 'derived_workflow',
        choices=c.WORKFLOW,
        allow_custom=False,
    ),
    FieldSpec('thumbnail_image_id', 'Project image', 'image'),
    FieldSpec('main_image_id', 'Main image', 'image_mirror'),
    FieldSpec('brand', 'Brand', 'brand'),
)

ACCELERATORS_SCHEMA = MetadataSchema(
    repo_key='accelerators',
    fields=_SHARED_FIELDS[:3] + (
        FieldSpec(
            'algorithm', 'Algorithm', 'single_choice',
            choices=c.ALGORITHM,
            cli_flag='--algorithm',
            cli_help='Supervised learning algorithm.',
            cli_choices=c.ALGORITHM,
        ),
    ) + _SHARED_FIELDS[3:] + (
        FieldSpec('links', 'Project links', 'accelerator_links'),
    ),
)

MODEL_ZOO_PSOC_SCHEMA = MetadataSchema(
    repo_key='model-zoo-psoc',
    fields=_SHARED_FIELDS + (
        FieldSpec('links', 'Project links', 'model_zoo_psoc_links'),
        FieldSpec('metrics', 'Performance metrics', 'metrics', required=False),
    ),
)

SCHEMAS: dict[str, MetadataSchema] = {
    ACCELERATORS_SCHEMA.repo_key: ACCELERATORS_SCHEMA,
    MODEL_ZOO_PSOC_SCHEMA.repo_key: MODEL_ZOO_PSOC_SCHEMA,
}


def validate_metadata_schemas(target_repo_keys: set[str]) -> None:
    """Ensure every target repository has a metadata schema (and vice versa)."""
    schema_keys = set(SCHEMAS)
    missing = target_repo_keys - schema_keys
    extra = schema_keys - target_repo_keys
    if missing:
        raise ValueError(
            f'Missing metadata schema for target repo(s): {", ".join(sorted(missing))}',
        )
    if extra:
        raise ValueError(
            f'Metadata schema(s) without a target repo entry: {", ".join(sorted(extra))}',
        )
