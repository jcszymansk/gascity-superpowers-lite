+++
schema = "lite.card.v1"
id = "cal-st-set-time-worked"
kind = "tdd-feature"
files = [
  "core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/repo/EntryRepository.kt",
  "core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/repo/JsonEntryRepository.kt",
  "core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/repo/JsonEntryRepositoryTest.kt",
]
done_when = [
  "nix develop --command ./gradlew :core:jvmTest --tests 'io.github.jcszymansk.simpletracker.core.repo.JsonEntryRepositoryTest'",
  "nix develop --command ./gradlew :core:jvmTest",
]
+++

## Goal

The entry repository can replace the time of one entry with an exact `ElapsedTime`, through a new `setTimeWorked(id, timeWorked)` mutation. `resetTime` becomes a call to it with zero, so the two cannot drift apart.

## Interfaces

In `EntryRepository` (package `io.github.jcszymansk.simpletracker.core.repo`) add, after `resetTime`:

```kotlin
/** Replaces the time of one entry and keeps every other field and the order. */
fun setTimeWorked(id: EntryId, timeWorked: ElapsedTime): Outcome<Unit>
```

(import `io.github.jcszymansk.simpletracker.core.model.ElapsedTime`). Also change the interface's KDoc from "The four mutations plus the current list state." to "The entry mutations plus the current list state."

In `JsonEntryRepository`:

```kotlin
override fun resetTime(id: EntryId): Outcome<Unit>   // now delegates: setTimeWorked(id, ElapsedTime.ZERO)
override fun setTimeWorked(id: EntryId, timeWorked: ElapsedTime): Outcome<Unit>
```

Behaviour of `setTimeWorked`, identical to what `resetTime` does today except for the value written:
- unknown id: `Outcome.Err(AppError.EntryNotFound(id))`, no store write;
- known id: the same list with only that entry's `timeWorked` replaced (order and other fields unchanged), encoded and written through the store, state published only after the write succeeded;
- failed write: the store's `Err` is returned and the state stays as before;
- failed-load repository: `Outcome.Err(AppError.RepositoryUnavailable)`, no write attempt.

## Context

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/repo/EntryRepository.kt` (lines 1-17):

```kotlin
package io.github.jcszymansk.simpletracker.core.repo

import io.github.jcszymansk.simpletracker.core.Outcome
import io.github.jcszymansk.simpletracker.core.model.EntryFields
import io.github.jcszymansk.simpletracker.core.model.EntryId
import io.github.jcszymansk.simpletracker.core.model.TimeEntry
import kotlinx.coroutines.flow.StateFlow

/** The four mutations plus the current list state. Confined to the UI thread. */
interface EntryRepository {
    val state: StateFlow<EntryListState>

    fun add(fields: EntryFields): Outcome<TimeEntry>
    fun edit(id: EntryId, fields: EntryFields): Outcome<Unit>
    fun delete(id: EntryId): Outcome<Unit>
    fun resetTime(id: EntryId): Outcome<Unit>
}
```

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/repo/JsonEntryRepository.kt` lines 59-98 (`ElapsedTime` is already imported at line 5; `JsonEntryRepository` is the only implementation of `EntryRepository`):

```kotlin
    override fun delete(id: EntryId): Outcome<Unit> = onReady { entries ->
        if (entries.none { it.id == id }) {
            Outcome.Ok(Unit)
        } else {
            publish(entries.filterNot { it.id == id })
        }
    }

    override fun resetTime(id: EntryId): Outcome<Unit> = onReady { entries ->
        val index = entries.indexOfFirst { it.id == id }
        if (index < 0) {
            return@onReady Outcome.Err(AppError.EntryNotFound(id))
        }
        publish(
            entries.mapIndexed { position, entry ->
                if (position == index) {
                    entry.copy(timeWorked = ElapsedTime.ZERO)
                } else {
                    entry
                }
            },
        )
    }

    private fun publish(next: List<TimeEntry>): Outcome<Unit> {
        val document = codec.encode(next)
        return when (val written = store.write(document)) {
            is Outcome.Err -> written
            is Outcome.Ok -> {
                mutableState.value = EntryListState.Ready(next)
                Outcome.Ok(Unit)
            }
        }
    }

    private inline fun <T> onReady(block: (List<TimeEntry>) -> Outcome<T>): Outcome<T> =
        when (val current = mutableState.value) {
            is EntryListState.Ready -> block(current.entries)
            is EntryListState.Failed -> unavailable()
        }
```

`ElapsedTime` (`core/.../model/ElapsedTime.kt`, lines 11-40): `@JvmInline value class ElapsedTime private constructor(val value: Long)` with `ElapsedTime.ZERO` and `ElapsedTime.of(seconds: Long): Outcome<ElapsedTime>` (Ok for 0..35_999_999). `TimeEntry(id: EntryId, project: ProjectName, task: TaskName, timeWorked: ElapsedTime)` is a data class.

Existing test file `core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/repo/JsonEntryRepositoryTest.kt`:
- imports at lines 3-16 (no `ElapsedTime` import yet; it must be added, alphabetically before `EntryFields`);
- the `reset zeroes the time and keeps the entry` test starts at line 72 and `a failed resetTime write leaves the state unchanged` at lines 160-174 (use it as the model for a failed-write test: `val (repository, before) = repositoryWithTwoEntries(store)`, `store.writeResult = Outcome.Err(failure)`, then `assertEquals(before, ready(repository).entries)`, `assertEquals(3, store.writeAttempts)`, `assertEquals(2, store.writes.size)`);
- `a failed load makes the repository read-only` at lines 176-187 asserts `Outcome.Err(AppError.RepositoryUnavailable)` for each mutation and ends with `assertEquals(0, store.writeAttempts)`;
- helpers at the bottom: `open(store)`, `repositoryWithTwoEntries(store)` (entries "simpletracker"/"design pass"/1:30 and "ntrecv"/"alert routing"/0:45), `ready(repository)`, `fields(project, task, time)`, `FakeStore` (fields `writes`, `writeAttempts`, `writeResult`), `SequentialIds`; the codec is `private val codec = JsonEntryDocumentCodec()` and `codec.decode(store.writes.last())` returns `Outcome<List<TimeEntry>>`.

The `core` module compiles with `allWarningsAsErrors = true`; no unused imports or variables.

## Steps

1. In `JsonEntryRepositoryTest.kt` add the `ElapsedTime` import and a private helper `seconds(value: Long): ElapsedTime` (unwrap `ElapsedTime.of(value)` with `assertIs<Outcome.Ok<ElapsedTime>>`) next to `fields`.
2. Add four tests after `a failed resetTime write leaves the state unchanged`:
   - `setTimeWorked replaces only the time and persists exact seconds`: add two entries, call `setTimeWorked` on the second with 2745 seconds, assert the second entry equals `target.copy(timeWorked = newTime)`, the first is untouched (project `"simpletracker"`, 5400 seconds), the list still has two entries, and decoding `store.writes.last()` gives 2745 seconds for the second entry;
   - `setTimeWorked on an unknown id returns EntryNotFound and writes nothing`;
   - `a failed setTimeWorked write leaves the state unchanged`, modelled on the resetTime one with `seconds(1)`;
   - `resetTime is a zero-time setTimeWorked`: add one entry with 1:30, `resetTime` it, assert the time is 0 and that `store.writes.last()` contains `"timeWorkedSeconds": 0`.
3. In `a failed load makes the repository read-only` add an assertion that `repository.setTimeWorked(EntryId("id-1"), seconds(60))` returns `Outcome.Err(AppError.RepositoryUnavailable)`, before the final `writeAttempts` assertion.
4. Run the first done_when command and confirm it fails (compile error: no `setTimeWorked`).
5. Add the method to `EntryRepository` and update its KDoc and imports. In `JsonEntryRepository` make `setTimeWorked` hold the existing lookup/replace/publish logic, parameterised on `timeWorked`, and reduce `resetTime` to a one-line delegation to it with `ElapsedTime.ZERO`. Do not duplicate the lookup logic.
6. Run both done_when commands; both must exit 0.

## Out of scope

- Do not touch the timer package, the desktop module, the codec or `EntryStore`; nothing else needs `setTimeWorked` yet.
- Do not change the behaviour of `add`, `edit` or `delete`.
- If another class turns out to implement `EntryRepository` and fails to compile, or any test fails before your change, stop and report it as a blocker with the command and the last 20 lines of output.
