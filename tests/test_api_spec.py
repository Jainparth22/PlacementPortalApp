"""The OpenAPI file must be valid and must match the routes the app really serves (contract test)."""
import os
import re

import pytest
import yaml
from openapi_spec_validator import validate

from conftest import ROOT

SPEC = os.path.join(ROOT, 'api.yaml')
UNDOCUMENTED_OK = {'/api/docs', '/api/swagger', '/api/openapi.yaml'}


class _NoDuplicateKeys(yaml.SafeLoader):
    pass


def _construct(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        assert key not in seen, f'duplicate YAML key: {key!r}'
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_NoDuplicateKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct)


@pytest.fixture(scope='module')
def spec():
    with open(SPEC, encoding='utf-8') as f:
        return yaml.load(f, Loader=_NoDuplicateKeys)


def test_spec_is_valid_openapi_without_duplicate_keys(spec):
    validate(spec)


def _flask_routes(app):
    out = {}
    for rule in app.url_map.iter_rules():
        path = rule.rule
        if not path.startswith('/api/') or path in UNDOCUMENTED_OK:
            continue
        doc_path = '/api/v1/' + path[len('/api/'):]
        doc_path = re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', doc_path)
        out.setdefault(doc_path, set()).update(m.lower() for m in rule.methods if m not in ('HEAD', 'OPTIONS'))
    return out


def test_every_served_endpoint_is_documented_and_vice_versa(app, spec):
    served = _flask_routes(app)
    documented = {p: {m for m in ops if m in ('get', 'post', 'put', 'delete', 'patch')}
                  for p, ops in spec['paths'].items() if p.startswith('/api/v1/')}
    missing_in_spec = {f'{m.upper()} {p}' for p, ms in served.items() for m in ms if m not in documented.get(p, set())}
    missing_in_app = {f'{m.upper()} {p}' for p, ms in documented.items() for m in ms if m not in served.get(p, set())}
    assert not missing_in_spec, f'served but not documented in api.yaml: {sorted(missing_in_spec)}'
    assert not missing_in_app, f'documented but not served: {sorted(missing_in_app)}'


def test_every_secured_operation_declares_bearer_auth(spec):
    for path, ops in spec['paths'].items():
        for method, op in ops.items():
            if method in ('get', 'post', 'put', 'delete') and op.get('security') is not None:
                assert op['security'], (path, method)
