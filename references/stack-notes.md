# Stack-specific traps

Read only the sections for the stacks the PR touches. Each is a list of things that are easy to miss in a diff and expensive in production, with how to spot them.

Contents

1. TypeScript and JavaScript (Node)
2. React and Next.js
3. Python
4. Go
5. Rust
6. Java and Kotlin
7. SQL and migrations
8. Docker, CI and Terraform
9. Shell scripts
10. Mobile (Swift, Kotlin/Android, React Native, Flutter)

---

## 1. TypeScript and JavaScript (Node)

- **Floating promises.** A call to an async function whose result is neither awaited nor returned nor `.catch`ed: errors vanish and ordering breaks. Look for `async` functions called as statements. Lint rule `@typescript-eslint/no-floating-promises` if the repo has it.
- **`await` in a loop** where the iterations are independent; `Promise.all` on a user-sized array without a concurrency limit (`p-limit` or batching).
- **Error handling.** `catch (e)` where `e` is `unknown` and treated as `Error`; rethrow losing the cause (`new Error(msg)` without `{ cause }`); `process.on('unhandledRejection')` swallowing everything.
- **Types that lie.** `as` casts, `any`, `!` non-null assertions, `@ts-ignore`/`@ts-expect-error`, `Record<string, any>`. Each is a place where the compiler was told to stop helping; ask what makes it safe.
- **`==` versus `===`**, `typeof null === "object"`, `Array.isArray`, `NaN !== NaN`, `0`/`""` falsy checks that should be `== null`.
- **Mutation.** `sort()`, `reverse()`, `splice()` mutate in place; spread copies are shallow; objects passed into functions and mutated.
- **Date.** `new Date("2024-01-01")` is UTC but `new Date("2024-01-01T00:00")` is local; month is zero-based; prefer the project's date library.
- **Node specifics.** Streams without error handlers, `fs.readFileSync` on a hot path, `child_process.exec` with interpolated input (`execFile` with args instead), `JSON.parse` on untrusted input without try/catch or size limits, `Buffer` from user length.
- **Dependencies.** New packages: exact name, maintained, size (`bundlephobia`), install scripts. `package-lock.json`/`pnpm-lock.yaml` consistent with `package.json` (CI with `npm ci` will fail if not).
- **Module boundaries.** Circular imports (runtime `undefined`), default versus named export mix-ups, ESM/CJS interop (`.default`).
- **Config.** `tsconfig` `strict` not weakened; `skipLibCheck` changes; `target` compatible with the runtime.

## 2. React and Next.js

- **Effects.** Missing or wrong dependency arrays; effects doing data fetching without cancellation (set state after unmount or on a stale request); effects for derived state that should be computed during render.
- **Keys.** Index as key on reorderable lists; non-unique keys.
- **State.** Derived state stored and desynchronised; state updates based on stale values (`setCount(count + 1)` in a loop instead of the functional form); objects recreated every render passed to memoised children.
- **Memoisation.** `useMemo`/`useCallback` added without a measured reason (cost and bugs, no benefit), or missing where a child's `React.memo` depends on it.
- **Server versus client (Next.js App Router).** Secrets or server-only imports in a Client Component; `"use client"` added to a tree that did not need it (bundle size); `fetch` cache options (`no-store`, `revalidate`) matching the data's freshness needs; Server Actions validating input and authorization (they are public endpoints).
- **Routing and data.** Dynamic routes trusting params; `redirect`/`notFound` after side effects; loading and error boundaries for new routes.
- **Accessibility.** `div` with `onClick`, missing `aria-*` on custom controls, focus not moved to opened dialogs, images without `alt`, icon-only buttons without labels, colour as the only signal.
- **Forms.** Controlled/uncontrolled mix; submit not disabled during pending; validation messages not associated with fields.
- **Security.** `dangerouslySetInnerHTML` with user content; `href={userUrl}` without scheme check (`javascript:`); tokens in `localStorage` if the codebase uses cookies.
- **Performance.** Large lists without virtualisation; images without `next/image` or sizing; client-side fetch for data available at the server; big dependencies imported into client bundles.

## 3. Python

- **Mutable defaults.** `def f(items=[])`, `def f(when=datetime.now())` (evaluated once).
- **Exceptions.** Bare `except:` or `except Exception:` that `pass` or log and continue; catching too early; `raise` versus `raise e` (traceback loss) versus `raise ... from e` (keep cause).
- **Typing.** `Optional` that is never checked; `Any` where a type exists; `# type: ignore` without an error code; `dict` used where a `dataclass`/`TypedDict`/pydantic model exists.
- **Async.** Blocking calls (`requests`, `time.sleep`, file I/O) inside `async def`; coroutine never awaited (a `RuntimeWarning` nobody reads); `asyncio.gather` without `return_exceptions` consideration; tasks created and not stored (garbage collected mid-flight).
- **Strings and bytes.** Mixing them; `.encode()` without an encoding; `str(path)` versus `Path`.
- **Iteration.** Modifying a list while iterating it; exhausting a generator twice; `zip` silently truncating (`strict=True` on 3.10+).
- **Resources.** Files, connections and locks without `with`; `tempfile` not cleaned up.
- **Dependencies.** `requirements.txt`/`pyproject`/lockfile consistent; pinned versions per project policy; new package exists on PyPI under that exact name.
- **Django.** `QuerySet` evaluated in a loop (N+1; `select_related`/`prefetch_related`); `.update()` versus `.save()` (signals, `auto_now`); migrations auto-generated with a rename detected as drop+create; `transaction.atomic` around multi-step writes; `on_commit` for side effects; `settings` changed without `DEBUG`-safe defaults; raw SQL with `%s` params not f-strings; `mark_safe`.
- **FastAPI / Flask.** Dependencies/decorators for auth present on every new route; pydantic models for all input; background tasks that outlive the request handled; `Depends` with cached singletons.
- **Scripts and CLIs.** `if __name__ == "__main__"`; `argparse` defaults; `subprocess` with `shell=True` and interpolated input; `os.system`.
- **Tests.** `pytest` fixtures with hidden state; `mock.patch` targeting the wrong import path (patching where it is defined instead of where it is used); `assert` on a mock call instead of behavior; `freezegun`/`time-machine` for time.

## 4. Go

- **Errors.** `err` ignored (`_`), shadowed (`err :=` inside an `if` block), checked after use, wrapped without `%w`, compared with `==` instead of `errors.Is`/`errors.As`. `panic` in library code.
- **Goroutines.** Leak on early return (no context cancellation, unbuffered channel nobody reads); loop variable captured (pre-1.22 semantics); `sync.WaitGroup` `Add` inside the goroutine; unbounded fan-out.
- **Context.** Not passed through; `context.Background()` deep in a call tree; deadline not set on outbound calls; `ctx` stored in a struct.
- **Maps and slices.** Concurrent map writes (fatal); `append` aliasing (`b := a[:2]; append(b, x)` overwrites `a[2]`); nil map write; nil versus empty slice in JSON (`null` versus `[]`).
- **Defer.** In a loop (runs at function end, not iteration end); `defer f.Close()` ignoring the error on writes; `defer` evaluation of arguments at defer time.
- **Interfaces.** Nil pointer in a non-nil interface; large interfaces instead of small ones; returning concrete types where the codebase returns interfaces (or vice versa).
- **HTTP.** `http.Client` without `Timeout`; response body not closed or not drained; `http.DefaultClient` for production traffic; handler writing after `WriteHeader`.
- **Database.** `rows.Close()`; `rows.Err()` after the loop; `sql.Tx` not rolled back on error; `QueryRow` versus `Query`.
- **Modules.** `go.sum` consistent (`GOTOOLCHAIN=local go mod tidy -diff` prints nothing, `go mod verify` says all modules verified; without `GOTOOLCHAIN=local` the first command may try to download the toolchain named in `go.mod`, and either may download the module graph, so run them in the background on a big repo); `replace` directives left in; new module's import path is the maintained fork; the `/go.mod` hash in `go.sum` unchanged means no transitive dependency moved.
- **Tests.** `t.Parallel()` with shared state; table tests missing the failing case; `testing.Short()`; golden files regenerated wholesale.

## 5. Rust

- **`unwrap`/`expect`/indexing** on values that can fail at runtime (user input, I/O, parsing) rather than on invariants; `?` where an error should be handled or enriched (`anyhow::Context`, `thiserror`).
- **`unsafe`.** Each block has a `// SAFETY:` comment stating the invariant and why it holds; the invariant is actually upheld by the surrounding code; no `unsafe` to silence the borrow checker.
- **Clones and allocation** in hot paths (`.clone()`, `.to_string()`, `collect()` into intermediate `Vec`s); `String` where `&str` would do; `Box<dyn Trait>` where generics are fine.
- **Concurrency.** `Mutex` held across `.await` (use the async runtime's mutex or restructure); `Arc<Mutex<>>` where a channel is clearer; `Rc`/`RefCell` crossing threads (will not compile, but `unsafe impl Send` might appear).
- **Async.** Blocking calls in async context (`std::fs`, `std::thread::sleep`); `tokio::spawn` without a `JoinHandle` being awaited or aborted; cancellation safety of `select!` branches.
- **Error types.** Public functions returning `Box<dyn Error>` or `anyhow::Error` in a library; error enums without `#[non_exhaustive]` when they are public.
- **Integer arithmetic.** Overflow (`wrapping_`, `checked_`, `saturating_` intent); `as` casts truncating; `usize` from untrusted lengths.
- **Lifetimes and API.** `'static` bounds added to make things compile; `pub` fields that break invariants; `Default` or `Clone` derived on types holding resources.
- **Cargo.** `Cargo.lock` committed for binaries; features additive; new crate maintained and not a typosquat; `build.rs` changes read carefully.
- **Clippy** warnings suppressed (`#[allow]`) without a reason.

## 6. Java and Kotlin

- **Null.** Java: `Optional` misuse (as a field, `.get()` without check), `@Nullable` ignored, NPE on auto-unboxing. Kotlin: `!!`, platform types from Java APIs treated as non-null, `lateinit` accessed early.
- **Equality.** `==` on boxed types or strings in Java; `equals`/`hashCode` not overridden together; mutable fields in `hashCode`; Kotlin `data class` with arrays.
- **Exceptions.** Checked exceptions wrapped and lost; `catch (Exception e) {}`; `finally` swallowing the original; resources without try-with-resources / `use {}`.
- **Concurrency.** `synchronized` on the wrong object or missing on one of several accesses; `HashMap` shared across threads; double-checked locking without `volatile`; `ExecutorService` never shut down; `CompletableFuture` exceptions unobserved. Kotlin coroutines: `GlobalScope`, `runBlocking` on a main/UI thread, missing `withContext(Dispatchers.IO)` for blocking calls, structured concurrency broken by `launch` in the wrong scope, `Dispatchers.Main` in a library.
- **Collections.** Mutating an unmodifiable view; `ConcurrentModificationException`; `List.of` null elements; streams with side effects.
- **Spring / frameworks.** `@Transactional` on a private or self-invoked method (no proxy, no transaction); lazy loading outside a session; `@Async` on the same class; field injection hiding dependencies; security annotations (`@PreAuthorize`) missing on new endpoints; `@Scheduled` without a lock in multi-instance deployments.
- **Serialization.** Jackson unknown properties, polymorphic type handling (`@JsonTypeInfo` with user-controlled types is a known RCE class), Java serialization of untrusted input.
- **Build.** Gradle/Maven dependency added with a dynamic version (`+`, `latest`); transitive conflicts; new plugin from an unknown source.
- **Kotlin style.** Scope functions nested three deep; `?.let` chains hiding a null path that should be an error; extension functions on common types in a shared module.

## 7. SQL and migrations

- **Locking.** Which statements take which locks on this engine and version, and for how long on the largest table affected. Postgres: `ALTER TABLE ... ADD COLUMN ... DEFAULT <volatile>`, `SET NOT NULL` (scan), `CREATE INDEX` without `CONCURRENTLY`, `ALTER TYPE`. MySQL: online DDL support varies; `pt-online-schema-change`/`gh-ost` where the project uses them.
- **Transactions.** `CREATE INDEX CONCURRENTLY` cannot run inside one; some migration frameworks wrap every migration in one by default. Mixed DDL and DML in one migration.
- **Ordering across deploys.** Expand (add nullable column, dual write), migrate (backfill in batches), contract (drop old) in separate releases.
- **Backfills.** Batched by primary key range, idempotent, resumable, throttled, not in the schema migration. `UPDATE t SET x = y` on a large table is an outage.
- **Indexes.** Serve the new `WHERE`/`JOIN`/`ORDER BY` columns in the right order; partial or expression indexes where the query filters on a function (`lower(email)`); not redundant with an existing composite; write amplification on hot tables.
- **Constraints.** Unique constraints for invariants the application also checks (the application check races); foreign keys with the intended `ON DELETE`; `CHECK` constraints for enums the application assumes; `NOT VALID` then `VALIDATE` for adding constraints to big tables in Postgres.
- **Types.** `timestamp` versus `timestamptz`; `float` for money; `varchar(n)` limits versus `text`; `serial` versus `identity`/`bigint` for IDs; JSON columns with no schema.
- **Data loss.** Dropping or renaming columns while old code is live; changing a type with implicit truncation; `DELETE`/`UPDATE` without `WHERE` or with a `WHERE` that matches more than intended (`NULL` handling, `IN` with an empty list).
- **Queries in application code.** `SELECT *`; missing `LIMIT`; `OFFSET` pagination on big tables; functions on indexed columns in `WHERE` (defeats the index); implicit casts; `NOT IN` with nullable subqueries; string-built SQL.
- **Reversibility.** The down migration exists, is tested, and the description says if it loses data.

## 8. Docker, CI and Terraform

- **Dockerfile.** Base image pinned (tag plus digest where the project does that) and still maintained; `USER` non-root; secrets not in `ARG`/`ENV`/layers (use build secrets); `COPY . .` with a `.dockerignore` that excludes `.git`, `.env`, `node_modules`; `apt-get update` and `install` in one `RUN` with cache cleanup; `HEALTHCHECK`; `latest` tags; multi-stage build keeps compilers out of the runtime image; `EXPOSE` matches the app.
- **Compose and Kubernetes.** Resource requests and limits; liveness versus readiness semantics; secrets from a secret store, not a ConfigMap; `imagePullPolicy`; rolling update strategy compatible with the migration plan; PodDisruptionBudget for anything that matters.
- **GitHub Actions and CI.** `permissions:` minimal and explicit; `pull_request_target` or `workflow_run` never checking out and running PR code with secrets available; third-party actions pinned to a commit SHA; `${{ github.event.* }}` values not interpolated into `run:` scripts (script injection; use `env:`); secrets not echoed; caches keyed on lockfiles; `continue-on-error` hiding failures; matrix still covers what it did; new steps run on the intended events and branches only.
- **Terraform and IaC.** Read the plan, not the diff: `destroy`/`replace` on stateful resources (databases, buckets, volumes); renames that move state (`moved` blocks); IAM policies widened (`*` actions or resources); security groups opened (`0.0.0.0/0`); encryption, versioning, logging, deletion protection turned off; provider and module versions pinned; `lifecycle { prevent_destroy }` on data stores; variables with sensitive values marked `sensitive`.
- **Secrets everywhere.** New environment variables added to every environment's secret store, the example file updated without the real value, rotation story if the secret is new.

## 9. Shell scripts

- `set -euo pipefail` (and `IFS` where word-splitting matters); `shellcheck` clean.
- Quoting: every variable expansion quoted unless splitting is intended; arrays for argument lists.
- `rm -rf "$DIR"/*` where `DIR` can be empty or unset (`${DIR:?}`); `cd` without checking success before destructive commands; `mktemp` for temp files and a `trap` to clean up.
- `[ ]` versus `[[ ]]`, `==` in `[ ]`, string versus numeric comparison, `-e` versus `-f`/`-d`.
- Portability: bashisms in `#!/bin/sh`; GNU-only flags (`sed -i`, `readlink -f`) on macOS targets; `which` versus `command -v`.
- `curl | sh`, unpinned downloads, missing checksum verification, `sudo` inside scripts.
- Exit codes meaningful; errors to stderr; `--help`; idempotent on rerun.

## 10. Mobile

- **General.** Work on the main/UI thread (network, database, JSON parsing); lifecycle (leaks from retained contexts, listeners not removed, coroutines/tasks not cancelled on destroy); offline and poor-network behavior; permissions requested with rationale and handled when denied; sensitive data in logs or unencrypted storage; deep links validated; API versions and OS versions supported.
- **Swift / iOS.** Force unwraps on runtime data; retain cycles in closures (`[weak self]`); `@MainActor` isolation; `Task` cancellation; `Codable` with optional fields that the backend may omit; Keychain versus `UserDefaults` for secrets; background task expiry.
- **Kotlin / Android.** `Context` leaks (activity held by a singleton); `lifecycleScope`/`viewModelScope` versus `GlobalScope`; `Dispatchers.IO` for blocking; configuration changes (rotation) resetting state; `RecyclerView` adapters with unstable IDs; `SharedPreferences` for secrets (use `EncryptedSharedPreferences`/Keystore); exported components (`android:exported`) and intent filters; permissions in the manifest matching the runtime requests; ProGuard/R8 rules for reflection-based libraries.
- **React Native / Flutter.** Bridge or platform-channel calls in render loops; large lists without virtualisation (`FlatList`, `ListView.builder`); platform-specific code paths tested on both; native dependency changes (Podfile.lock, Gradle) consistent; state management conventions of the project followed.
