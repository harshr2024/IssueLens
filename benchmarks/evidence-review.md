# Flask duplicate-evidence audit

Audited against GitHub's REST API on 2026-09-27. Each evidence comment was
retrieved directly by its `issuecomment` ID. Comment text below is verbatim;
line endings are normalized to LF for this Markdown file. No approval values
were changed, and this report contains no authentication credentials.

## Summary

- 15/15 evidence comments were found and attached to the expected source issue.
- 10 comments clearly call the source a duplicate of the configured target.
- 1 comment uses qualified language: “looks like a duplicate.”
- 1 comment asks whether the source is a “possible duplicate.”
- 3 comments name a target in another repository, not the configured Flask target.
- No configured source or target is a pull request.
- No same-repository target-number mismatch was found.

## Pair review

### `flask-5901-3747`

- Source: [#5901 — Flask's blueprint's render templates rendering another blueprint's folder's html file !!!](https://github.com/pallets/flask/issues/5901)
- Target: [#3747 — blueprint does not render template relative to the blueprint.](https://github.com/pallets/flask/issues/3747)
- Comment: [davidism](https://github.com/pallets/flask/issues/5901#issuecomment-3797892707) (`MEMBER`)
- Verdict: **Yes.** “Duplicate of #3747” directly identifies the configured target. “And others” does not weaken that identification.
- Flags: None.

~~~~text
https://flask.palletsprojects.com/en/stable/blueprints/#templates

Duplicate of #3747 and others
~~~~

### `flask-5642-371`

- Source: [#5642 — PROVIDE_AUTOMATIC_OPTIONS causes KeyError if not set](https://github.com/pallets/flask/issues/5642)
- Configured target: [pallets/flask#371 — Quickstart: Unique URLs / Redirection Behaviour](https://github.com/pallets/flask/issues/371)
- Comment: [davidism](https://github.com/pallets/flask/issues/5642#issuecomment-2476702272) (`MEMBER`)
- Verdict: **No.** The comment explicitly names `pallets/quart#371`, not `pallets/flask#371`.
- Flags: **Wrong target repository.** The matching number alone does not establish this benchmark pair.

~~~~text
Duplicate of pallets/quart#371
~~~~

### `flask-4994-3404`

- Source: [#4994 — route decorator compatibility with MethodView](https://github.com/pallets/flask/issues/4994)
- Target: [#3404 — route decorator on MethodView classes](https://github.com/pallets/flask/issues/3404)
- Comment: [davidism](https://github.com/pallets/flask/issues/4994#issuecomment-1441830506) (`MEMBER`)
- Verdict: **Yes.** The configured target is explicitly included in the “Duplicate of” list.
- Flags: None; the comment also names other duplicate targets.

~~~~text
Duplicate of #3404, #3975, #4817
~~~~

### `flask-4990-4734`

- Source: [#4990 — app.test_client is not thread-safe](https://github.com/pallets/flask/issues/4990)
- Target: [#4734 — Version 2.2.0 crashes when using app.test_client() as a context-manager in multi-threaded tests](https://github.com/pallets/flask/issues/4734)
- Comment: [davidism](https://github.com/pallets/flask/issues/4990#issuecomment-1438573317) (`MEMBER`)
- Verdict: **Yes.** The opening sentence directly identifies the configured target.
- Flags: None.

~~~~text
Duplicate of #4734

Do not push the client globally around all tests, that's not the correct way to use it. Only push the client if you need to preserve the `request` global after a test request is evaluated, and _only_ around the code that needs it. In your example, you do not need to push the client at all, only created it.

```python
client = app.test_client()
```
~~~~

### `flask-4817-3404`

- Source: [#4817 — Class Blueprint](https://github.com/pallets/flask/issues/4817)
- Target: [#3404 — route decorator on MethodView classes](https://github.com/pallets/flask/issues/3404)
- Comment: [davidism](https://github.com/pallets/flask/issues/4817#issuecomment-1245672024) (`MEMBER`)
- Verdict: **Yes.** The configured target is explicitly included in the “Duplicate of” list.
- Flags: None; the comment also names another duplicate target.

~~~~text
Duplicate of #3404, #3975

Register blueprints with `app.add_url_rule("/path", endpoint="name", view_func=View.as_view())`. I do not plan to allow using `@app.route` on `View` classes, as it would prevent passing args and kwargs to `as_view`, and would be a special case over any other API extension. Extensions are free to provide whatever methods they like for defining an API.
~~~~

### `flask-4931-4928`

- Source: [#4931 — Documentation: "flask --app hello run --debug" no longer works](https://github.com/pallets/flask/issues/4931)
- Target: [#4928 — Docs are incorrect about how to run a debug server](https://github.com/pallets/flask/issues/4928)
- Comment: [davidism](https://github.com/pallets/flask/issues/4931#issuecomment-1367488370) (`MEMBER`)
- Verdict: **Yes.** The configured target is explicitly included in the “Duplicate of” list.
- Flags: None; the comment also names another duplicate target.

~~~~text
Duplicate of #4928, #4930.

> Really, no changes since 2010?

A year in a copyright notice is not a last updated timestamp.
~~~~

### `flask-4456-4455`

- Source: [#4456 — Breaking change in markupsafe makes flask crash on service startup](https://github.com/pallets/flask/issues/4456)
- Target: [#4455 — Pinning Flask<2 requires pinning ItsDangerous<2.1 and MarkupSafe<2.1](https://github.com/pallets/flask/issues/4455)
- Comment: [davidism](https://github.com/pallets/flask/issues/4456#issuecomment-1044530631) (`MEMBER`)
- Verdict: **Yes.** The opening sentence directly identifies the configured target.
- Flags: None.

~~~~text
Duplicate of #4455 

You are using an unsupported version of Flask and Jinja, please update to the latest version. Additionally, please read https://hynek.me/articles/semver-will-not-save-you/, then use a tool like [pip-tools](https://pypi.org/project/pip-tools/) to pin your dependencies and control when you get updates. Be sure to run your tests with deprecation warnings treated as errors so that you get notified of these types of changes early.
~~~~

### `flask-4434-4307`

- Source: [#4434 — PR #4283 broke traceback on import errors.](https://github.com/pallets/flask/issues/4434)
- Target: [#4307 — "an ImportError was raised" but flask doesn't show the traceback](https://github.com/pallets/flask/issues/4307)
- Comment: [davidism](https://github.com/pallets/flask/issues/4434#issuecomment-1025159295) (`MEMBER`)
- Verdict: **Yes.** The comment directly identifies the configured target.
- Flags: None. The source title mentions a PR, but the source itself is an issue.

~~~~text
Duplicate of #4307
~~~~

### `flask-4351-4307`

- Source: [#4351 — ImportError when trying to start flask app, but no stack trace printed](https://github.com/pallets/flask/issues/4351)
- Target: [#4307 — "an ImportError was raised" but flask doesn't show the traceback](https://github.com/pallets/flask/issues/4307)
- Comment: [davidism](https://github.com/pallets/flask/issues/4351#issuecomment-974670686) (`MEMBER`)
- Verdict: **Yes.** The comment directly identifies the configured target.
- Flags: None.

~~~~text
Duplicate of #4307
~~~~

### `flask-4137-3545`

- Source: [#4137 — `create_app` is not used in testing docs](https://github.com/pallets/flask/issues/4137)
- Target: [#3545 — Testing docs are out of date](https://github.com/pallets/flask/issues/3545)
- Comment: [davidism](https://github.com/pallets/flask/issues/4137#issuecomment-855424065) (`MEMBER`)
- Verdict: **Yes.** The comment directly identifies the configured target.
- Flags: None.

~~~~text
Duplicate of #3545
~~~~

### `flask-4086-4069`

- Source: [#4086 — Registering a blueprint does not update the url_prefix](https://github.com/pallets/flask/issues/4086)
- Target: [#4069 — Nested blueprint should be able to have same name](https://github.com/pallets/flask/issues/4069)
- Comment: [pgjones](https://github.com/pallets/flask/issues/4086#issuecomment-845905888) (`MEMBER`)
- Verdict: **Yes.** The comment directly identifies the configured target; the second reference is a fixing pull request, not the duplicate target.
- Flags: None.

~~~~text
Duplicate of #4069, fixed by #4074
~~~~

### `flask-4038-4020`

- Source: [#4038 — _AppCtxGlobals causes `assigning-non-slot` warning from pylint and mypy](https://github.com/pallets/flask/issues/4038)
- Target: [#4020 — Assigning to attribute flask.g.[...] not defined in class slots (assigning-non-slot)](https://github.com/pallets/flask/issues/4020)
- Comment: [ThiefMaster](https://github.com/pallets/flask/issues/4038#issuecomment-840548939) (`MEMBER`)
- Verdict: **Qualified yes.** The comment explicitly relates this source to the configured target, but “looks like” is a hedge rather than an unqualified duplicate declaration.
- Flags: **Ambiguous/qualified language.** Manual approval should account for that uncertainty.

~~~~text
This looks like a duplicate of #4020

> If we're not supposed to be setting random properties there any more then the docs probably need fixing. maybe we're supposed to use `db = g.setdefault("db", connect_to_database())` now?

Assigning `g.whatever` is still the way to go. The linter warning is a false positive.
~~~~

### `flask-2768-2741`

- Source: [#2768 — Traceback shown when running `flask` without any args or an app](https://github.com/pallets/flask/issues/2768)
- Target: [#2741 — Better exception handling when env vars are missing for flask CLI](https://github.com/pallets/flask/issues/2741)
- Comment: [davidism](https://github.com/pallets/flask/issues/2768#issuecomment-387737774) (`MEMBER`)
- Verdict: **No definitive assertion.** The comment asks whether it is a possible duplicate; it does not state that the source duplicates the target.
- Flags: **Ambiguous language.** This is materially weaker than “Duplicate of #2741.”

~~~~text
Didn't it originally only show the error message then someone made a PR adding the traceback? I'm wary of removing the traceback, since it could contain information about import or syntax errors.

Possible duplicate of #2741?
~~~~

### `flask-1736-16`

- Source: [#1736 — Documentation download links for PDF and zipped HTML return 404s on http://flask.pocoo.org/](https://github.com/pallets/flask/issues/1736)
- Configured target: [pallets/flask#16 — Add easy way to set session expiry](https://github.com/pallets/flask/issues/16)
- Comment: [ThiefMaster](https://github.com/pallets/flask/issues/1736#issuecomment-187238704) (`MEMBER`)
- Verdict: **No.** The comment explicitly names `mitsuhiko/flask-website#16`, not `pallets/flask#16`.
- Flags: **Wrong target repository.** The matching number alone does not establish this benchmark pair.

~~~~text
duplicate of mitsuhiko/flask-website#16

~~~~

### `flask-1251-7`

- Source: [#1251 — Flask Doc Download Link Broken](https://github.com/pallets/flask/issues/1251)
- Configured target: [pallets/flask#7 — Visibility on pocoo.org](https://github.com/pallets/flask/issues/7)
- Comment: [davidism](https://github.com/pallets/flask/issues/1251#issuecomment-63975499) (`MEMBER`)
- Verdict: **No.** The comment names `pocoo/metaflask#7`, not `pallets/flask#7`; “other duplicates” refers to other reports of that external issue.
- Flags: **Wrong target repository.** This is a duplicate reference elsewhere, not evidence for the configured Flask pair.

~~~~text
Duplicate of all the other duplicates of pocoo/metaflask#7.

~~~~
