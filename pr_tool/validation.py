"""Project and metadata validation before publishing."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import constants
from metadata import finalize_metadata
from metadata.choices import (
    BRAND_IMAGE_ID,
    METRIC_LABELS,
    brand_for_image,
    match_choice,
    normalize_project_types,
    workflow_for_types,
)
from metadata.schema import FieldSpec, MetadataSchema
from project_layouts import get_project_layout
from target_repo import TargetRepo

CollectMissingFn = Callable[[dict, set[str]], dict]


@dataclass
class MetadataValidationResult:
    missing: list[str] = field(default_factory=list)
    choice_violations: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    fields_to_collect: set[str] = field(default_factory=set)
    choice_fields: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.choice_violations and not self.other


def validate_project_structure(
    project_name: str, project_path: Path, target_repo: TargetRepo,
) -> None:
    """Validate the project folder before publishing."""
    get_project_layout(target_repo.project_layout).validate(project_name, project_path)


def validate_metadata(
    metadata: dict,
    schema: MetadataSchema,
    project_name: str | None = None,
) -> MetadataValidationResult:
    """Validate *metadata* against *schema*, splitting missing vs choice issues."""
    result = MetadataValidationResult()
    if not isinstance(metadata, dict):
        result.missing.append('metadata.json must be a JSON object')
        return result

    for spec in schema.fields:
        if spec.kind == 'brand':
            _validate_brand(metadata, spec, result)
        elif spec.kind == 'image':
            _validate_required_str(metadata, 'thumbnail_image_id', spec, result)
        elif spec.kind == 'image_mirror':
            _validate_image_mirror(metadata, spec, result)
        elif spec.kind in ('text', 'long_text'):
            _validate_text(metadata, spec, result)
        elif spec.kind == 'single_choice':
            _validate_single_choice(metadata, spec, result)
        elif spec.kind == 'multi_choice':
            _validate_multi_choice(metadata, spec, result)
        elif spec.kind == 'derived_workflow':
            _validate_derived_workflow(metadata, spec, result)
        elif spec.kind in ('accelerator_links', 'model_zoo_psoc_links'):
            _validate_links(metadata, spec, result, project_name)
        elif spec.kind == 'metrics':
            _validate_metrics(metadata, spec, result)
    return result


def validate_loaded_metadata(
    metadata: dict,
    schema: MetadataSchema,
    collect_missing: CollectMissingFn,
    project_name: str | None = None,
) -> dict:
    """Validate loaded metadata; prompt for missing fields, confirm on choice violations."""
    from metadata import confirm_metadata

    current = _repair_image_mirror(dict(metadata))
    while True:
        result = validate_metadata(current, schema, project_name)
        if result.missing or result.other:
            print(
                f'\n{constants.ICON_WARNING} Your project\'s metadata.json is missing '
                f'required fields or has values this tool cannot accept:',
            )
            for issue in result.missing + result.other:
                print(f'  - {issue}')
            print(f'\n{constants.ICON_INFO} Please provide the missing or corrected metadata below.')
            if not result.fields_to_collect:
                raise ValueError('metadata.json has issues that cannot be collected interactively')
            current = collect_missing(current, result.fields_to_collect)
            current = _repair_image_mirror(current)
            continue
        if result.choice_violations:
            print(
                f'\n{constants.ICON_WARNING} Your project\'s metadata.json uses values '
                f'that are not in this tool\'s suggested lists, which are based on the projects '
                f'already available in the DEEPCRAFT\u2122 AI Hub:',
            )
            for issue in result.choice_violations:
                print(f'  - {issue}')
            print(
                f'\n{constants.ICON_INFO} Common for new projects that use sensors, kits, '
                f'devices, applications, use cases, or algorithms not yet in the AI Hub '
                f'catalog, or if metadata.json was edited, copied, or saved before the '
                f'lists were updated.',
            )
            print(
                f'\n{constants.ICON_INFO} You did not see the suggested lists for these '
                f'fields on this run. If a value was meant to match an existing one, '
                f'choose redo (n) to browse the lists and pick from them. Choose yes (y) '
                f'only if you intend to keep these as new values.',
            )
            print()
            answer = confirm_metadata()
            if answer == 'abort':
                print(f'{constants.ICON_ABORT} Aborted by user.')
                sys.exit(0)
            if answer == 'no':
                current = collect_missing(current, result.choice_fields)
                current = _repair_image_mirror(current)
                continue
        return finalize_metadata(current, schema)


def _repair_image_mirror(metadata: dict) -> dict:
    from metadata.image_field import normalize_project_image_name

    thumb = metadata.get('thumbnail_image_id')
    if isinstance(thumb, str) and thumb.strip():
        thumb = normalize_project_image_name(thumb)
        metadata['thumbnail_image_id'] = thumb
        metadata['main_image_id'] = thumb
    elif isinstance(metadata.get('main_image_id'), str) and metadata['main_image_id'].strip():
        metadata['main_image_id'] = normalize_project_image_name(metadata['main_image_id'])
    return metadata


def _mark_missing(result: MetadataValidationResult, spec: FieldSpec, message: str) -> None:
    result.missing.append(message)
    result.fields_to_collect.add(spec.key)


def _mark_other(result: MetadataValidationResult, spec: FieldSpec, message: str) -> None:
    result.other.append(message)
    result.fields_to_collect.add(spec.key)


def _mark_choice(result: MetadataValidationResult, spec: FieldSpec, message: str) -> None:
    result.choice_violations.append(message)
    result.choice_fields.add(spec.key)


def _validate_required_str(
    metadata: dict,
    key: str,
    spec: FieldSpec,
    result: MetadataValidationResult,
) -> None:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        _mark_missing(result, spec, f'Missing or empty required field: {key}')


def _validate_text(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    value = metadata.get(spec.key)
    if not isinstance(value, str) or not value.strip():
        _mark_missing(result, spec, f'Missing or empty required field: {spec.key}')
        return
    if spec.max_length is not None and len(value) > spec.max_length:
        _mark_other(
            result,
            spec,
            f'{spec.key} exceeds max length of {spec.max_length} characters '
            f'(got {len(value)})',
        )


def _choice_list_hint(spec: FieldSpec) -> str:
    return f'{len(spec.choices)} allowed values'


def _validate_single_choice(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    value = metadata.get(spec.key)
    if not isinstance(value, str) or not value.strip():
        _mark_missing(result, spec, f'Missing or empty required field: {spec.key}')
        return
    if value in spec.choices:
        return
    matched = match_choice(value, spec.choices)
    if matched is not None:
        metadata[spec.key] = matched
        return
    _mark_choice(
        result, spec,
        f'{spec.key}: {value!r} is not in the allowed list ({_choice_list_hint(spec)})',
    )


def _validate_multi_choice(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    raw = metadata.get(spec.key)
    if spec.key == 'type':
        value = normalize_project_types(raw)
        if value and raw != value:
            metadata[spec.key] = value
    else:
        value = raw
    if value is None:
        _mark_missing(result, spec, f'Missing required field: {spec.key}')
        return
    if not isinstance(value, list) or not value:
        _mark_missing(result, spec, f'{spec.key} must be a non-empty list')
        return
    metadata[spec.key] = value
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            _mark_missing(result, spec, f'{spec.key} contains an invalid entry')
            return
        if item in spec.choices:
            continue
        matched = match_choice(item, spec.choices)
        if matched is not None:
            value[index] = matched
            continue
        _mark_choice(
            result, spec,
            f'{spec.key}: {item!r} is not in the allowed list ({_choice_list_hint(spec)})',
        )


def _validate_derived_workflow(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    types = normalize_project_types(metadata.get('type'))
    if not types:
        return
    expected = workflow_for_types(types)
    actual = metadata.get('workflow')
    if actual is None:
        metadata['workflow'] = expected
        return
    if not isinstance(actual, list) or not actual:
        _mark_missing(result, spec, f'{spec.key} must be a non-empty list')
        return
    if actual != expected:
        _mark_other(
            result,
            spec,
            f'{spec.key} does not match project type '
            f'(expected {expected!r}, got {actual!r})',
        )


def _validate_image_mirror(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    if not isinstance(metadata.get('main_image_id'), str) or not metadata['main_image_id'].strip():
        _mark_missing(result, spec, 'Missing or empty required field: main_image_id')


def _validate_brand(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    brand_image_id = metadata.get('brand_image_id')
    brand_url = metadata.get('brand_url')
    if not isinstance(brand_image_id, str) or not brand_image_id.strip():
        _mark_missing(result, spec, 'Missing or empty required field: brand_image_id')
        return
    if not isinstance(brand_url, str) or not brand_url.strip():
        _mark_missing(result, spec, 'Missing or empty required field: brand_url')
        return
    if brand_image_id not in BRAND_IMAGE_ID:
        _mark_choice(
            result, spec,
            f'brand_image_id: {brand_image_id!r} is not in the allowed list '
            f'({len(BRAND_IMAGE_ID)} known brands)',
        )
        return
    expected_url = brand_for_image(brand_image_id).brand_url
    if brand_url != expected_url:
        _mark_other(
            result,
            spec,
            f'brand_url does not match brand_image_id '
            f'(expected {expected_url!r}, got {brand_url!r})',
        )


def _validate_links(
    metadata: dict,
    spec: FieldSpec,
    result: MetadataValidationResult,
    project_name: str | None = None,
) -> None:
    links = metadata.get('links')
    if links is None:
        _mark_missing(result, spec, 'Missing required field: links')
        return
    if not isinstance(links, list) or not links:
        _mark_missing(result, spec, 'links must be a non-empty list')
        return
    for index, link in enumerate(links, start=1):
        if not isinstance(link, dict):
            _mark_missing(result, spec, f'links[{index}] must be an object')
            return
        for key in ('label', 'url', 'heading', 'sub-heading'):
            if not isinstance(link.get(key), str) or not link[key].strip():
                _mark_missing(result, spec, f'links[{index}] missing or empty {key!r}')
                return
        _repair_github_link_url(link, project_name)


def _repair_github_link_url(link: dict, project_name: str | None) -> None:
    """Silently align a GitHub project link's trailing path segment with *project_name*."""
    if not project_name:
        return
    marker = '/tree/main/'
    url = link['url']
    if link.get('label') != 'GitHub' or marker not in url:
        return
    base, _, _tail = url.partition(marker)
    corrected = f'{base}{marker}{project_name}'
    if corrected != url:
        link['url'] = corrected


def _validate_metrics(metadata: dict, spec: FieldSpec, result: MetadataValidationResult) -> None:
    metrics = metadata.get('metrics')
    if metrics is None:
        if spec.required:
            _mark_missing(result, spec, 'Missing required field: metrics')
        return
    if not isinstance(metrics, list) or not metrics:
        _mark_other(result, spec, 'metrics must be a non-empty list when present')
        return
    allowed_labels = set(METRIC_LABELS)
    for index, entry in enumerate(metrics, start=1):
        if not isinstance(entry, dict):
            _mark_other(result, spec, f'metrics[{index}] must be an object')
            return
        label = entry.get('label')
        value = entry.get('value')
        if not isinstance(label, str) or label not in allowed_labels:
            _mark_choice(
                result, spec,
                f'metrics[{index}] label {label!r} is not allowed '
                f'(expected one of {len(METRIC_LABELS)} predefined labels)',
            )
        if not isinstance(value, str) or not value.strip():
            _mark_missing(result, spec, f'metrics[{index}] missing or empty value')
