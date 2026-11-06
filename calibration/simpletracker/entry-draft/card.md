+++
schema = "lite.card.v1"
id = "cal-st-entry-draft"
kind = "tdd-feature"
files = [
  "core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/draft/EntryDraft.kt",
  "core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/draft/EntryDraftTest.kt",
]
done_when = [
  "nix develop --command ./gradlew :core:jvmTest --tests 'io.github.jcszymansk.simpletracker.core.draft.EntryDraftTest'",
  "nix develop --command ./gradlew :core:jvmTest",
]
+++

## Goal

A form's three raw strings can be turned into validated `EntryFields` by one call that reports the first failure, checking project, then task, then time, so the UI can show a single inline message.

## Interfaces

New file `core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/draft/EntryDraft.kt`, package `io.github.jcszymansk.simpletracker.core.draft`:

```kotlin
data class EntryDraft(
    val project: String,
    val task: String,
    val timeWorked: String,
) {
    fun validate(): Outcome<EntryFields>
}
```

`validate()` behaviour:
- Validates `project` with `ProjectName.of`, then `task` with `TaskName.of`, then `timeWorked` with `TimeInput.parse`. The first `Outcome.Err` is returned unchanged; later fields are not looked at.
- When all three pass, returns `Outcome.Ok(EntryFields(projectName, taskName, minutes))`.
- Names come back trimmed (that is done by `ProjectName.of` and `TaskName.of`); time text may have surrounding spaces (done by `TimeInput.parse`).

## Context

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/EntryFields.kt` (lines 1-8):

```kotlin
package io.github.jcszymansk.simpletracker.core.model

/** Validated values of one entry form, ready for the repository. */
data class EntryFields(
    val project: ProjectName,
    val task: TaskName,
    val timeWorked: Minutes,
)
```

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/ProjectName.kt` (lines 7-24; `TaskName.kt` is identical with `TaskName`, `AppError.BlankTask` and `NameField.TASK`):

```kotlin
/** A trimmed, non-blank project name of at most 200 characters. */
@JvmInline
value class ProjectName private constructor(val value: String) {
    companion object {
        const val MAX_LENGTH = 200

        fun of(raw: String): Outcome<ProjectName> {
            val trimmed = raw.trim()
            if (trimmed.isEmpty()) {
                return Outcome.Err(AppError.BlankProject)
            }
            if (trimmed.length > MAX_LENGTH) {
                return Outcome.Err(AppError.TooLong(NameField.PROJECT, MAX_LENGTH))
            }
            return Outcome.Ok(ProjectName(trimmed))
        }
    }
}
```

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/TimeInput.kt` (the `H:MM` parser, already present):

```kotlin
object TimeInput {
    fun parse(raw: String): Outcome<Minutes>   // Err(AppError.InvalidTime(raw)) on bad text
    fun format(minutes: Minutes): String
}
```

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/Outcome.kt` (lines 7-10):

```kotlin
sealed interface Outcome<out T> {
    data class Ok<out T>(val value: T) : Outcome<T>
    data class Err(val error: AppError) : Outcome<Nothing>
}
```

`AppError` (same package, `AppError.kt` lines 20-24) has `BlankProject`, `BlankTask` (data objects), `TooLong(field: NameField, max: Int)` and `InvalidTime(raw: String)`; `NameField` is an enum with `PROJECT` and `TASK`, in `io.github.jcszymansk.simpletracker.core`.

Test style used elsewhere (for example `core/src/commonTest/.../model/MinutesTest.kt`): `kotlin.test.Test`, `assertEquals`, `assertIs`; backticked sentence test names; `assertIs<Outcome.Ok<X>>(result)` to unwrap, `assertEquals(Outcome.Err(AppError.InvalidTime("-1")), result)` for failures.

The `core` module compiles with `allWarningsAsErrors = true`; remove unused imports. `commonMain` must not import `java.*`/`javax.*`.

## Steps

1. Create `EntryDraftTest.kt` under `core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/draft/` (package `io.github.jcszymansk.simpletracker.core.draft`), class `EntryDraftTest`, with six tests:
   - valid draft `EntryDraft(project = "  simpletracker ", task = " design pass  ", timeWorked = " 1:30 ")` gives Ok with project `"simpletracker"`, task `"design pass"` and `timeWorked.value == 90L`;
   - blank project with a blank task and bad time reports `AppError.BlankProject`;
   - valid project, blank task, bad time reports `AppError.BlankTask`;
   - 201-character project reports `AppError.TooLong(NameField.PROJECT, 200)`;
   - 201-character task reports `AppError.TooLong(NameField.TASK, 200)`;
   - valid names with time `"1:60"` reports `AppError.InvalidTime("1:60")`.
2. Run the first done_when command and watch it fail (the class does not exist).
3. Create `EntryDraft.kt` with the data class and KDoc stating the validation order. Implement `validate()` by unwrapping each of the three results in turn with `when (val result = ...)`, returning the `Err` immediately, so no later field is validated after a failure.
4. Run both done_when commands; both must exit 0.

## Out of scope

- No changes outside the two listed files: not `EntryFields`, the name types, `TimeInput`, the repository, or the desktop UI.
- No exceptions for control flow and no nulls; use the `Outcome` the validators already return.
- If an existing test fails before you change anything, or the toolchain cannot run, stop and report it as a blocker with the command and the last 20 lines of output.
