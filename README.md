# Repo Cassette Private Solver

This directory is prepared for the GitHub account that creates the CTF instance.
Keep the repository private. The instance OAuth token must be able to read this
same private repository and its Actions artifacts.

Build the artifacts before requesting an instance. Instances only last about five
minutes.

## 1. Create the private repository

```bash
cd /home/yujeong/repo-cassette-solver
git init
git add .
git commit -m "Add Repo Cassette solver"
gh repo create repo-cassette-private --private --source . --push
```

`gh auth status` must show the same GitHub account that will be connected to the
Repo Cassette instancer.

## 2. Build artifacts

```bash
gh workflow run build.yml --repo OWNER/repo-cassette-private
RUN_ID=$(gh run list --repo OWNER/repo-cassette-private --workflow build.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --repo OWNER/repo-cassette-private --exit-status
```

The workflow performs 32 races between artifact version 6 with the NEL-prefixed
JSON MIME and artifact version 7 with raw delivery. The local solver tries every
result automatically because the metadata state selected by GitHub is race
dependent.

## 3. Request and solve an instance

Request the instance from the same public IP that will run `solve.py`. The
instancer rejects clients coming from another IP.

```bash
python3 solve.py http://repo-archive.chal.hitconctf.com:PORT OWNER/repo-cassette-private
```

The solver performs the following steps:

1. Lists the private Actions artifacts through the local GitHub login.
2. Imports a HAR whose repository path escapes into the artifact download API.
3. Finds a candidate accepted by both the Node and Python MIME parsers.
4. Triggers the postcard portrait fetch for `file:///proc/self/environ`.
5. Decodes the embedded SVG data URI and prints the flag.

Do not use a repository owned by a teammate unless they explicitly authorize it.
