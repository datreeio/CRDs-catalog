import base64
import copy
import datetime as dt
import json
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import crd_policy as p
import crd_publish as publisher

SHA = 'a' * 40
FILE = 'example.io/widget_v1.json'
URL = 'https://github.com/example/operator/blob/' + SHA + '/config/crd.yaml'
BODY = '```crd-sources\n' + json.dumps({FILE: URL}) + '\n```'
NOW = dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc)
CRD = b'''apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
spec:
  group: example.io
  names: {kind: Widget}
  versions: [{name: v1}]
'''


class FakeAPI:
    repository = 'datreeio/CRDs-catalog'

    def __init__(self):
        self.pr = {'number': 1, 'head': {'sha': SHA, 'repo': {'full_name': 'person/catalog'}}, 'base': {'sha': 'b' * 40, 'ref': 'main'}, 'body': BODY, 'state': 'open', 'draft': False, 'changed_files': 1}
        self.files = [{'filename': FILE, 'status': 'added', 'sha': 'c' * 40}]
        self.metadata = {'created_at': '2020-01-01T00:00:00Z', 'stargazers_count': 5}
        self.raw = b'{"type":"object","properties":{"spec":{"type":"object"}}}'
        self.mode = '100644'
        self.calls = []
        self.reviews = []
        self.changed_on_read = None
        self.reads = 0

    def request(self, path, data=None, method=None):
        self.calls.append((path, data, method))
        if path.endswith('/pulls/1'):
            self.reads += 1
            if self.changed_on_read == self.reads:
                self.pr['body'] += '\nchanged'
            return copy.deepcopy(self.pr)
        if path.endswith('/git/ref/heads/main'):
            return {'object': {'sha': 'b' * 40}}
        if path.endswith('/merge'):
            return {'merged': True}
        if path.endswith('/reviews') and data:
            self.reviews.append({'id': 7, 'user': {'login': 'github-actions[bot]'}, 'state': 'APPROVED', 'body': data['body']})
            return {'id': 7}
        if path.endswith('/dismissals'):
            self.reviews.clear()
        return {}

    def pages(self, path, **kwargs):
        if path.endswith('/files'):
            return self.files
        if path.endswith('/reviews'):
            return list(self.reviews)
        return []

    def get(self, path):
        return self.metadata

    def entry(self, repo, commit, path):
        return {'type': 'blob', 'mode': self.mode, 'size': len(self.raw), 'sha': 'c' * 40}

    def blob(self, repo, entry, maximum):
        if entry['mode'] != '100644' or len(self.raw) > maximum:
            raise p.PolicyError('manual-review', 'Invalid mode/size')
        return CRD if repo == 'example/operator' else self.raw


class PolicyTests(unittest.TestCase):
    def expect_error(self, decision, fn, *args):
        with self.assertRaises(p.PolicyError) as cm:
            fn(*args)
        self.assertEqual(cm.exception.decision, decision)

    def test_eligible_new_group(self):
        self.assertEqual(p.evaluate(FakeAPI(), 1, NOW)['decision'], 'eligible')

    def test_missing_source(self):
        api = FakeAPI(); api.pr['body'] = 'homepage only'
        self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'needs-contributor-input')

    def test_threshold_boundaries(self):
        meta = {'created_at': (NOW-dt.timedelta(days=30)).isoformat(), 'stargazers_count': 5}
        p.repository_eligible(meta, NOW)
        for age, stars in [(29, 5000), (5000, 4)]:
            meta.update(created_at=(NOW-dt.timedelta(days=age)).isoformat(), stargazers_count=stars)
            self.expect_error('manual-review', p.repository_eligible, meta, NOW)

    def test_low_stars_manual(self):
        api = FakeAPI(); api.metadata['stargazers_count'] = 4
        self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'manual-review')

    def test_mutating_pr(self):
        api = FakeAPI(); api.changed_on_read = 2
        self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'needs-contributor-input')

    def test_no_deletions_renames_workflows_or_traversal(self):
        for status, name in [('removed', FILE), ('renamed', FILE), ('modified', '.github/workflows/pwn.yml'), ('added', '../widget_v1.json'), ('added', 'example.io/a/b.json')]:
            api = FakeAPI(); api.files[0].update(status=status, filename=name)
            self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'manual-review')

    def test_count_limit(self):
        api = FakeAPI(); api.pr['changed_files'] = 26
        self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'manual-review')

    def test_mode_limit(self):
        for mode in ['120000', '100755', '160000']:
            api = FakeAPI(); api.mode = mode
            self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'manual-review')

    def test_file_size_limit(self):
        api = FakeAPI(); api.raw = b' ' * (p.MAX_FILE + 1)
        self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'manual-review')

    def test_json_schema_validation(self):
        for raw in [b'{', b'{"type":"object","type":"string"}', b'{"type":"object","required":"a"}', b'{"type":"object","maximum":NaN}', b'{"type":"object","$schema":"https://evil.test/schema"}', b'{"type":"object","$ref":"https://evil.test/schema"}', b'{"type":"object","$dynamicRef":"other.json"}']:
            self.expect_error('needs-contributor-input', p.validate_schema, raw)
        p.validate_schema(b'{"type":"object","definitions":{"x":{"type":"string"}},"properties":{"a":{"$ref":"#/definitions/x"}}}')

    def test_sources_exact_mapping(self):
        for body in ['', BODY+'\n'+BODY, BODY.replace(FILE, 'other.io/widget_v1.json'), BODY.replace(SHA, 'main'), BODY.replace('github.com/', 'github.com.evil.test/'), BODY.replace('/config/', '/../'), BODY.replace(URL, URL+'?token=foo')]:
            self.expect_error('needs-contributor-input', p.parse_sources, body, [FILE])
        self.assertEqual(p.parse_sources(BODY, [FILE])[FILE], ('example/operator', SHA, 'config/crd.yaml'))

    def test_human_source_table(self):
        table = '| Schema file | Source CRD |\n| --- | --- |\n| `' + FILE + '` | ' + URL + ' |\n'
        expected = p.parse_sources(BODY, [FILE])
        self.assertEqual(p.parse_sources(table, [FILE]), expected)
        for invalid in [table + table, table + BODY, table + '| `' + FILE + '` | ' + URL + ' |\n', table.replace(SHA, 'main'), table.replace(URL, 'Paste the permanent GitHub file link here')]:
            self.expect_error('needs-contributor-input', p.parse_sources, invalid, [FILE])

    def test_rendered_template_source_mapping(self):
        template = (pathlib.Path(__file__).resolve().parents[2] / 'pull_request_template.md').read_text()
        filled = template.replace('Paste the permanent GitHub file link here', URL)
        self.assertEqual(p.parse_sources(filled, [FILE]), p.parse_sources(BODY, [FILE]))

    def test_crd_identity(self):
        self.assertEqual(p.source_identities(CRD), {('example.io', 'widget', 'v1')})
        self.assertEqual(p.source_identities(CRD.replace(b'CustomResourceDefinition', b'Deployment')), set())

    def test_yaml_no_objects_or_aliases(self):
        for raw in [b'!!python/object/apply:os.system [echo nope]', b'a: &a [*a]']:
            self.expect_error('needs-contributor-input', p.source_identities, raw)

    def test_wrong_source_identity(self):
        api = FakeAPI(); api.pr['body'] = BODY.replace(FILE, 'example.io/other_v1.json'); api.files[0]['filename'] = 'example.io/other_v1.json'
        self.assertEqual(p.evaluate(api, 1, NOW)['decision'], 'needs-contributor-input')

    def test_blob_symlink_and_size(self):
        api = p.GitHub('x/y')
        self.expect_error('manual-review', api.blob, 'x/y', {'type':'blob','mode':'120000'}, 100)
        self.expect_error('manual-review', api.blob, 'x/y', {'type':'blob','mode':'100644','size':101}, 100)

    def test_snapshot_includes_body_head_base_draft(self):
        api = FakeAPI(); original = p.snapshot(api.pr)
        for field, value in [('body','new'), ('draft',True), ('state','closed')]:
            clone = copy.deepcopy(api.pr); clone[field] = value
            self.assertNotEqual(original, p.snapshot(clone))
        for field in ['head','base']:
            clone = copy.deepcopy(api.pr); clone[field]['sha'] = 'd'*40
            self.assertNotEqual(original, p.snapshot(clone))


class PublisherTests(unittest.TestCase):
    def report(self, api, decision='eligible'):
        return {'number':1,'head':SHA,'snapshot':p.snapshot(api.pr),'decision':decision,'reason':'Test'}

    @patch.object(publisher, 'announce')
    def test_manual_never_approves(self, _):
        for decision in ['manual-review', 'needs-contributor-input', 'error']:
            api = FakeAPI(); publisher.publish(api, self.report(api, decision), 'b'*40, True)
            self.assertFalse(any(data and data.get('event') == 'APPROVE' for path, data, method in api.calls))

    @patch.object(publisher, 'announce')
    def test_activation_switch(self, _):
        api = FakeAPI(); publisher.publish(api, self.report(api), 'b'*40, False)
        self.assertFalse(any(path.endswith('/merge') for path, data, method in api.calls))

    @patch.object(publisher, 'announce')
    def test_exact_head_merge(self, _):
        api = FakeAPI(); publisher.publish(api, self.report(api), 'b'*40, True)
        merges = [data for path, data, method in api.calls if path.endswith('/merge')]
        self.assertEqual(merges, [{'sha':SHA,'merge_method':'squash'}])

    @patch.object(publisher, 'announce')
    def test_no_merge_after_body_edit(self, _):
        api = FakeAPI(); api.changed_on_read = 3
        publisher.publish(api, self.report(api), 'b'*40, True)
        self.assertFalse(any(path.endswith('/merge') for path, data, method in api.calls))
        self.assertTrue(any(path.endswith('/dismissals') for path, data, method in api.calls))

    @patch.object(publisher, 'announce')
    def test_stale_policy_no_approval(self, _):
        api = FakeAPI(); publisher.publish(api, self.report(api), 'd'*40, True)
        self.assertFalse(api.reviews)

    def test_restricted_dismissal_supersedes_own_approval(self):
        import urllib.error
        api = FakeAPI()
        api.reviews = [{'id':7,'user':{'login':'github-actions[bot]'},'state':'APPROVED','body':publisher.REVIEW_MARKER}]
        original = api.request
        def restricted(path, data=None, method=None):
            if path.endswith('/dismissals'):
                raise urllib.error.HTTPError('https://api.github.com',403,'Forbidden',{},None)
            return original(path,data,method)
        api.request = restricted
        publisher.withdraw(api, 1)
        self.assertTrue(any(data and data.get('event') == 'REQUEST_CHANGES' for path,data,method in api.calls))

    @patch.object(publisher.time, 'sleep')
    @patch.object(publisher, 'announce')
    def test_failed_merge_withdraws_approval(self, *_):
        import urllib.error
        api = FakeAPI(); original = api.request
        def blocked(path, data=None, method=None):
            if path.endswith('/merge'):
                raise urllib.error.HTTPError('https://api.github.com',405,'Blocked',{},None)
            return original(path,data,method)
        api.request = blocked
        publisher.publish(api, self.report(api), 'b'*40, True)
        self.assertFalse(api.reviews)

    def test_does_not_dismiss_human_review(self):
        api = FakeAPI(); api.reviews = [{'id':2,'user':{'login':'human'},'state':'APPROVED','body':publisher.REVIEW_MARKER}]
        publisher.withdraw(api, 1)
        self.assertEqual(len(api.reviews),1)


if __name__ == '__main__':
    unittest.main()
