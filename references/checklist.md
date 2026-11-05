# The review checklist, by concern

How to use this file: do not walk it top to bottom on every PR. Pick the sections the change touches (`summary.md` lists risk flags per file), and for each item ask the two questions that matter: *does this apply here?* and *how would I know?* Each item says how to check, because "check for races" is not actionable and "find every read-then-write on shared state and ask what happens when two requests interleave" is.

Contents

1. Design and scope
2. Correctness
3. Error handling and failure paths
4. Concurrency and async
5. Data, schemas and migrations
6. APIs and contracts
7. Security
8. Performance
9. Reliability and operations
10. Observability
11. Tests
12. Readability and maintainability
13. Dependencies and supply chain
14. Configuration, infrastructure and CI
15. Frontend and UI
16. Documentation
17. Rollout and rollback

---

## 1. Design and scope

- **Does the change solve the stated problem, and only that?** Compare the diff with the linked issue or description. Unrelated refactors, renames and formatting churn hide the real change and make bisecting harder; ask for them to move to their own PR unless they are tiny and necessary.
- **Is this the right place and the right layer?** Business rules in a controller, SQL in a view, HTTP concerns in a domain model. How to check: look at how the neighbouring code of the same kind is organised and whether the new code follows it.
- **Is there an existing utility, pattern or abstraction this duplicates?** Grep the repository for the operation being implemented (retry, pagination, date parsing, slugify, money rounding). Duplicates diverge and the second copy is the one that will be wrong in a year.
- **Is the abstraction earned?** A new interface with one implementation, a plugin system with one plugin, a config option nobody asked for. Ask what concrete second case justifies it; if there is none, the simpler version is better.
- **Will this still make sense to the next reader?** Can you explain the design in two sentences? If not, the author probably cannot either, and the PR description should.
- **Should this have been a design discussion?** If you find yourself writing a long architectural comment, say so at the top and offer to talk; do not nitpick a design you think should change.

## 2. Correctness

- **Boundaries.** For every loop, slice, pagination and range: empty input, one element, the exact limit, limit plus one. Off-by-one shows up in `<` versus `<=`, `len - 1`, inclusive versus exclusive ends, and page math.
- **Absent values.** `null`/`None`/`undefined`, empty string, empty collection, zero, and the difference between "missing" and "explicitly empty". Check that optional fields are optional all the way down (type, validation, database column, serializer).
- **Numbers.** Integer overflow in languages that have it, division by zero, negative inputs where only positives were imagined, floats for money or anything compared with `==`, rounding mode (banker's versus half-up) and where rounding happens (per line or on the total).
- **Text.** Unicode: length in bytes versus code points versus grapheme clusters, case folding (`ß`, Turkish `i`), normalisation (NFC/NFD) before comparison, right-to-left, emoji in names. Encoding at every boundary (file, HTTP, database).
- **Time.** Time zones and DST (a day is not always 24 hours), naive versus aware datetimes, leap years and leap seconds, month arithmetic (Jan 31 + 1 month), clock skew between services, `now()` called twice in one operation, timestamps compared across zones, retention math.
- **Ordering and identity.** Code that assumes map or set iteration order, stable sort, unique IDs, or that two floats compare equal. Equality versus identity (`==` versus `is`, `equals` versus `==`).
- **State and aliasing.** Functions that mutate their arguments or shared/global state; a cached object handed to a caller who mutates it; default mutable arguments in Python; reusing a buffer across iterations.
- **Branch coverage by reading.** For every `if`, ask what happens in the `else`, including the implicit one. For every `switch`, ask about the default and about new enum members added later.
- **Copy-paste.** Two near-identical blocks: diff them in your head. The one that was pasted usually still has the first one's variable.
- **The claimed behavior.** Read the description's claims ("handles retries", "backwards compatible", "no behavior change") as hypotheses and look for the code that makes each one true.

## 3. Error handling and failure paths

- **What happens on the exception?** For each call that can fail (I/O, network, parsing, database, external API), find where its failure is handled and what the user or caller sees. Unhandled is sometimes right; silent is almost never right.
- **Catch-alls.** `except Exception`, `catch (e) {}`, `_ = err`, `.catch(() => {})`. Ask what specific failure the author expected and whether the handler is correct for *every* failure it now also catches (including programming errors it now hides).
- **Partial failure.** A loop that writes ten records and fails on the sixth. A two-step write (database then queue, file then index). What state is left, who retries, and is the retry safe?
- **Cleanup.** Files, sockets, locks, transactions, temp dirs, timers and subscriptions released on every path, including the error path. Look for `finally`, `defer`, `with`, `using`, `try-with-resources`, or their absence.
- **Idempotency.** If this runs twice (retry, double click, duplicate message), is the result the same? Payment, email, provisioning and counters are where this bites.
- **Error messages.** Do they say what failed, with which input, and what to do about it? Do they leak internals (stack traces, SQL, file paths, secrets) to end users? Are they logged once, not at every layer?
- **Timeouts.** Every network call, subprocess and lock acquisition has a bound. "It has a default" is only an answer if you looked up the default (many are infinite).
- **Validation at the boundary.** Input from users, files, other services and the database is checked once, at the edge, and trusted inside. Validation scattered through the core is a sign it is missing somewhere.

## 4. Concurrency and async

- **Read-then-write.** `if not exists: create`, `balance = get(); set(balance - x)`, `count += 1` on shared state. Ask what happens when two requests interleave. The fix is usually a transaction, a unique constraint, an atomic operation or a lock; check which one the codebase uses elsewhere.
- **Locks.** Acquired in a consistent order (deadlock), held across I/O (latency and starvation), released on error paths, and actually protecting the data they claim to (same lock for every access).
- **Transactions.** Scope covers every write that must be atomic, and nothing slow. Isolation level is enough for the invariant (`REPEATABLE READ` does not stop phantom inserts). Work queued inside a transaction (emails, jobs) happens after commit, not before.
- **Async hygiene.** Forgotten `await` (the call runs but its result and errors are lost), `await` inside a loop where a gather would do, blocking calls on an event loop, unbounded `Promise.all` or goroutine fan-out over user-controlled lists, cancellation that is never checked.
- **Shared mutable state.** Module-level caches, singletons, class attributes, request-scoped data stored on something longer-lived. Thread safety of the structures used (a Python `dict` is not a safe counter; a Go `map` is not safe for concurrent writes).
- **Ordering across workers.** Messages processed out of order, at-least-once delivery handled as exactly-once, two workers picking the same job (`SELECT ... FOR UPDATE SKIP LOCKED` or equivalent).
- **Tests for concurrency** rarely exist. Ask for the invariant in a comment and, where the codebase has a pattern (a stress test, a deterministic scheduler), for a test.

## 5. Data, schemas and migrations

- **Rolling deploys.** Old code and new code run at the same time against the same database for minutes to hours. The new column must be nullable or defaulted until every writer sets it; the old column must stay until every reader is gone. Expand, migrate, contract: three deploys, not one.
- **Data in flight.** Queued messages, cached objects, serialized sessions and cookies created by the old code will be read by the new code. Check deserialisation of the old shape.
- **Locks and duration.** Adding a column with a default, adding an index, changing a type or adding a NOT NULL on a large table can lock it for the duration. Check the database and version: Postgres `ADD COLUMN ... DEFAULT` is fast since 11, `CREATE INDEX CONCURRENTLY` cannot run in a transaction, MySQL varies by engine and version.
- **Indexes.** Every new query pattern (new `WHERE`, `ORDER BY`, join or foreign key) has an index that serves it, and no new index is redundant with an existing composite one. Ask for `EXPLAIN` on anything that runs per request.
- **Backfills.** Batched, resumable, idempotent, throttled, and separate from the schema change. A backfill in a migration file blocks the deploy.
- **Reversibility.** Does the down migration exist and work? Is data dropped on the way down? Irreversible migrations are sometimes fine, but they should be labelled.
- **Constraints.** Uniqueness, foreign keys, check constraints and NOT NULL belong in the database when the invariant matters; application-level checks race. Case sensitivity of unique indexes on text.
- **Encoding, precision and types.** `float` for money, `varchar(255)` for URLs, `int` for IDs that will overflow, timestamps without time zone, JSON columns hiding a schema.
- **Deletions.** Soft versus hard delete matches the rest of the system; cascades are intended; a `DELETE` or `UPDATE` without a `WHERE` or with a `WHERE` on a nullable column.
- **ORM footguns.** Lazy loading in a loop (N+1), `save()` writing every column, migrations auto-generated from models that also renamed things (drop plus create instead of rename).

## 6. APIs and contracts

- **Breaking changes.** Removed or renamed field, changed type, new required parameter, changed default, changed error code or shape, changed ordering guarantees, tightened validation. Each one breaks some consumer. Grep for consumers (other services, SDKs, frontend, scripts, documentation examples).
- **Versioning and compatibility.** Additive changes are safe; everything else needs a version, a deprecation period or a feature flag. Check the project's stated policy.
- **Input validation and limits.** Size limits on bodies, arrays and strings; pagination with a maximum page size; rate limits on anything expensive; unknown fields rejected or ignored consistently.
- **Idempotency and retries.** Mutating endpoints that clients may retry accept an idempotency key or are naturally idempotent (`PUT` over `POST`).
- **Error contract.** Consistent error shape, correct status codes (a validation error is not a 500, a missing resource is not a 200 with `{error: ...}`), no internals in messages.
- **Pagination.** Cursor versus offset matches the data's churn; total counts are not computed on every page of a large table; the last page and an empty result are handled.
- **Events and messages.** Schema evolution (new fields optional, old fields never reused), ordering and duplication handled by consumers, payload size bounded.
- **CLI and config.** Flags, environment variables and config keys are contracts too: removing or renaming one breaks every script and deployment that uses it.
- **Documentation and examples** updated in the same PR, or the contract is whatever the code happens to do.

## 7. Security

Think in terms of trust boundaries: where does data cross from less trusted to more trusted, and what checks happen at that line.

- **Authentication and authorization on every new path.** Every new route, handler, GraphQL resolver, background job trigger, webhook and admin action checks *who* and *whether they may*, in the same way the rest of the codebase does (middleware, decorator, policy object). Object-level authorization: the user may list invoices, but may they read *this* invoice? Deny by default; look for the check, not for its absence.
- **Injection.** SQL built with string formatting or concatenation; shell commands built from input (`shell=True`, `exec`, backticks); paths built from input (`../`); template injection; header and log injection (newlines in logged input); LDAP, XPath, NoSQL operators (`{$gt: ""}`) in query objects built from JSON.
- **Output encoding.** HTML (`innerHTML`, `dangerouslySetInnerHTML`, `|safe`, `mark_safe`, `v-html`), URLs, JavaScript contexts, CSV formulas (`=cmd`), emails.
- **Server-side requests.** URLs from users fetched by the server (webhooks, image proxies, importers): allow-list schemes and hosts, block private ranges and redirects to them, bound response size and time.
- **Deserialization and parsing.** `pickle`, `yaml.load` without a safe loader, Java `ObjectInputStream`, PHP `unserialize`, XML with external entities, ZIP and tar extraction with path traversal, image parsers with untrusted input, regexes with catastrophic backtracking on user input.
- **Secrets.** Nothing that looks like a key, token, password or private key in code, fixtures, tests, URLs, logs or error messages. New secrets come from the same place the rest do (env, vault, secret manager), and the example config is updated without the real value.
- **Sensitive data.** PII, credentials and tokens are not logged, not put in URLs or query strings, not cached where they should not be, and are encrypted at rest when the rest of the system does so. Check new log lines and new error messages specifically.
- **Cryptography.** No home-grown crypto; current algorithms (no MD5/SHA-1 for security, no ECB, no static IVs); passwords hashed with a slow, salted hash (bcrypt, scrypt, argon2); constant-time comparison for secrets and signatures; randomness from a CSPRNG for anything security-relevant.
- **Sessions and tokens.** Expiry, rotation on privilege change, invalidation on logout and password change, cookie flags (`HttpOnly`, `Secure`, `SameSite`), CSRF protection on state-changing form posts, JWT algorithm pinned and signature verified.
- **Uploads and files.** Type validated by content not extension, size bounded, stored outside the web root or in object storage, served with a safe content type and disposition, filenames not trusted.
- **Dependencies.** New packages exist under exactly that name, are maintained, have the license the project allows and do not pull in a surprising tree. A typo'd or hallucinated package name is a supply-chain attack waiting for someone to register it.
- **Headers and transport.** TLS verification not disabled (`verify=False`, `rejectUnauthorized: false`, `InsecureSkipVerify`), security headers unchanged, CORS not opened to `*` with credentials.
- **Multi-tenancy.** Every query scoped by tenant, including the new one, including the background job, including the admin tool.
- **Audit.** Security-relevant actions (login, permission change, export, delete) logged with actor and target where the system already does so.

## 8. Performance

- **N+1.** A query, HTTP call or file read inside a loop over database results. Look for ORM relationship access in loops and for `for item in items: fetch(item.id)`.
- **Unbounded work.** Queries without `LIMIT`, loading a whole table or file into memory, recursion without depth bound, regexes on unbounded input, fan-out proportional to a user-controlled number.
- **Hot paths.** Code that runs per request, per row or per frame: allocation in loops, repeated parsing or compilation (regex compiled inside a function), logging with string formatting evaluated even when the level is off, synchronous I/O.
- **Caching.** Cache key includes everything the value depends on (tenant, locale, version); invalidation happens on every write path; TTL is appropriate; stampede protection where the miss is expensive.
- **Database.** Indexes serve the new queries (section 5); `SELECT *` on wide tables; sorting or distinct on unindexed columns; transactions held open across network calls.
- **Payload size.** APIs returning more fields than the client uses, images and bundles not optimised, pagination missing.
- **Measure, do not guess.** If the PR claims a speedup or you suspect a slowdown, ask for or produce a number. Premature optimisation that complicates code is also a finding.

## 9. Reliability and operations

- **Timeouts, retries, backoff.** Every outbound call has a timeout; retries are bounded, use backoff with jitter, and only retry idempotent operations or safe error classes; the total retry budget is less than the caller's timeout.
- **Graceful degradation.** What happens when the dependency (cache, search, third-party API) is down? Fail open or closed is a decision, made explicitly.
- **Resource limits.** Connection pools, thread pools, queue depths and memory are bounded and sized; new background work has a concurrency limit.
- **Startup and shutdown.** New long-running work drains on shutdown; health checks reflect readiness; migrations run before or after deploy as the system expects.
- **Feature flags and kill switches.** Risky behavior can be turned off without a deploy; the flag's default matches the rollout plan; the flag is removed later (add a TODO with an owner).
- **Configuration.** New config has a sane default, is validated at startup, and is documented; environment-specific values are not hard-coded.
- **Runbook.** Would the on-call engineer know this exists and what to do when it alerts? For new infrastructure or jobs, a line in the runbook or README.

## 10. Observability

- **Logs.** New code paths log enough to debug a failure (what was attempted, with which identifiers) and not so much that they drown the rest. Levels are right (`error` means someone should look). No PII or secrets (section 7). Structured fields where the codebase uses them.
- **Metrics.** New endpoints, jobs and external calls emit the same metrics the existing ones do (latency, count, errors). Counters for business events that matter.
- **Traces and correlation.** Request IDs propagate through new async boundaries and outbound calls.
- **Alerts.** New failure modes have an alert or are covered by an existing one; new noisy logs do not trigger existing alerts.
- **Errors.** Exceptions reach the error tracker with context, once.

## 11. Tests

- **Would it fail?** For each test, imagine the bug it is meant to catch and check the assertion would detect it. A test with no assertion, or that asserts the mock was called, often would not. Mutation thinking: delete a line of the production change in your head; which test goes red?
- **Behavior, not implementation.** Tests that assert internal call sequences or private state break on every refactor and pass on real bugs. Prefer input, output, observable side effect.
- **Coverage of the change.** New branches, error paths, boundaries and the bug being fixed (a regression test that fails without the fix). Not line coverage; case coverage.
- **Negative cases.** Invalid input rejected, unauthorized access denied, failure of a dependency handled.
- **Mocks.** Mock the boundary (network, clock, filesystem), not the unit under test and not the database when a real one is available. Over-mocked tests prove the mocks agree with themselves.
- **Flakiness.** Sleeps, real time, real network, shared global state, order dependence, randomness without a seed, tests that pass alone and fail together.
- **Readability.** Test names say the scenario and the expectation; setup is visible; one concept per test; failure messages would tell you what broke.
- **Test changes in the PR.** Deleted or weakened assertions, skipped tests, raised tolerances, snapshots regenerated wholesale. Each one needs a reason in the description.
- **Honesty.** Does CI actually run the new tests (right directory, right pattern, not excluded)? Is the "manually tested" claim credible and reproducible?

## 12. Readability and maintainability

- **Names.** Say what the thing is or does, at the right level of abstraction, consistent with the codebase (`fetch` versus `get` versus `load`, `user_id` versus `userId`). Booleans read as predicates. No `data`, `info`, `tmp`, `manager`, `util` for things that have a real name.
- **Functions.** Do one thing at one level of abstraction; are short enough to hold in your head; take few parameters (or a struct); do not use booleans to select behavior; return consistently.
- **Comments.** Explain why, not what; are correct after the change; no commented-out code; TODOs have an owner or a ticket.
- **Complexity.** Deep nesting, long conditionals, clever one-liners, flags that change control flow. Early returns, guard clauses and extracted predicates usually fix it.
- **Consistency.** The new code looks like it was written by the same team as the surrounding code: same error handling pattern, same logging, same layering, same naming. Consistency beats local preference.
- **Dead code.** Unused imports, parameters, branches, feature flags, files. Delete; version control remembers.
- **Duplication.** Three similar blocks are a function; two might be. A copy with one difference is a bug waiting to be fixed in only one place.
- **Magic values.** Literals with meaning (`86400`, `0.08`, `"admin"`) are named constants or configuration.
- **Types.** Where the language has them, they are used honestly: no `any`, `Object`, `interface{}` where a real type exists; nullable types reflect reality; narrow types for IDs and units when the codebase does that.

## 13. Dependencies and supply chain

- **Is it needed?** A dependency for something the standard library or an existing dependency already does is cost without benefit. Check for left-pad sized packages.
- **Is it the right one?** Exact name (typosquats and hallucinated names exist), actively maintained, reasonable download counts, known maintainers, compatible license, no install-time scripts doing surprising things.
- **Version pinning.** Matches the project's policy; lockfile updated and consistent with the manifest; no downgrade of a transitive dependency.
- **Bumps.** For a version bump, read the changelog between the two versions for breaking changes, deprecations and security notes. A major bump is a feature, not a chore.
- **Vulnerabilities.** Advisory databases or the project's scanner are clean for the new tree.
- **Size and footprint.** Bundle size for frontend, image size for containers, cold start for serverless.

## 14. Configuration, infrastructure and CI

- **CI changes.** New steps run on the right triggers, with the right permissions (`permissions:` blocks minimal, no `pull_request_target` with checkout of the PR head, no secrets exposed to forks), pinned actions (SHA, not tag, where the project does that), caches keyed correctly.
- **Dockerfiles.** Pinned base images, non-root user, no secrets in layers or build args, `.dockerignore` excludes what it should, multi-stage keeps the final image small, health check present.
- **Infrastructure as code.** Plan output reviewed for destroys and replacements; state-affecting renames; security groups and IAM narrowed, not widened; encryption and logging left on; resource tags and naming consistent.
- **Environment and config.** New variables documented and added to every environment and example file; defaults safe for production; no production values in the repo.
- **Scripts.** `set -euo pipefail` or the language's equivalent; quoting; no `rm -rf` on a variable that can be empty; idempotent where rerun is possible.
- **Permissions and ownership.** New files, buckets, queues and topics have the right access policies and an owner.

## 15. Frontend and UI

- **State.** Derived state computed, not stored; effects have correct dependencies and cleanup; race conditions when a request resolves after the component changed or unmounted; stale closures.
- **Rendering.** Lists have stable keys; expensive work memoised only when measured; no layout thrash; images sized.
- **Accessibility.** Semantic elements, labels on inputs, focus management in modals and route changes, keyboard operability, contrast, `alt` text, reduced motion respected, no `div` with an `onClick` doing a button's job.
- **Error, loading and empty states.** Each new data-driven view handles all three.
- **Forms.** Validation messages next to fields, submit disabled while pending, double-submit prevented, server errors surfaced.
- **Security.** No `dangerouslySetInnerHTML` with user content, URLs validated before use in `href`/`src`, tokens not in `localStorage` if the codebase avoids that.
- **Internationalisation.** New strings go through the translation layer if the app has one; dates, numbers and plurals formatted by locale; layout survives long translations and right-to-left.
- **Responsiveness and browsers.** Works at narrow widths; no use of APIs unsupported by the project's browser targets.
- **Design fidelity.** Matches the design or the existing component library; does not reinvent a component that exists.

## 16. Documentation

- **Updated with the change.** README, API docs, architecture notes, runbooks, CHANGELOG, migration guides, inline examples. Documentation that describes the old behavior is worse than none.
- **Public surface.** New public functions, endpoints, flags and config keys are documented where their siblings are.
- **The PR itself.** The description says why, what and how to verify; links the issue; shows screenshots for UI; notes risks and rollout. A future reader of `git blame` will land here.

## 17. Rollout and rollback

- **Order of operations.** Migration before or after code; flag default; consumers before producers for new events; clients before servers for stricter validation.
- **Rollback.** If this is reverted after an hour in production, what breaks? Data written in the new shape, messages in the new format, a dropped column.
- **Blast radius.** Who is affected if this is wrong: one tenant, one region, every user? Can it ship to a subset first?
- **Monitoring the rollout.** Which dashboard or metric shows this working? Who watches it?
- **Communication.** Does anyone need to know (support, other teams, customers)? Is a changelog entry needed?
