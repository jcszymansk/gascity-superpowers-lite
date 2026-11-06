+++
schema = "lite.card.v1"
id = "cal-st-time-input"
kind = "tdd-feature"
files = [
  "core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/Minutes.kt",
  "core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/TimeInput.kt",
  "core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/model/MinutesTest.kt",
  "core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/model/TimeInputTest.kt",
]
done_when = [
  "nix develop --command ./gradlew :core:jvmTest --tests 'io.github.jcszymansk.simpletracker.core.model.TimeInputTest' --tests 'io.github.jcszymansk.simpletracker.core.model.MinutesTest'",
  "nix develop --command ./gradlew :core:jvmTest",
]
+++

## Goal

Time worked can be typed and shown as `H:MM`. A new `TimeInput` object parses the text into `Minutes` and formats `Minutes` back to text, and `Minutes` is capped at 9999 hours 59 minutes so every value it can hold formats to text that parses back to the same value.

## Interfaces

New file `core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/TimeInput.kt`, package `io.github.jcszymansk.simpletracker.core.model`:

```kotlin
object TimeInput {
    fun parse(raw: String): Outcome<Minutes>
    fun format(minutes: Minutes): String
}
```

Changed in `Minutes` (same package), inside its `companion object`:

```kotlin
val MAX: Minutes          // 599_999 minutes = 9999:59
fun of(value: Long): Outcome<Minutes>   // now Ok only for 0..MAX.value, else Err(AppError.InvalidTime(value.toString()))
```

Format rules:
- `parse`: after `raw.trim()`, the text is hours (1 to 4 digits), a colon, and minutes (exactly 2 digits, `00` to `59`). Examples: `"0:00"` -> 0, `"1:30"` -> 90, `"25:00"` -> 1500, `" 2:05 "` -> 125, `"9999:00"` -> 599_940.
- Anything else is `Outcome.Err(AppError.InvalidTime(raw))` with `raw` exactly as passed in (not trimmed). Rejected examples: `"1:60"`, `"1"`, `"1:5"`, `":30"`, `"-1"`, `"abc"`, `""`, `"06:00:00"`, `"1:000"`, `"10000:00"`, `" 1:60 "`.
- `format`: hours without padding, a colon, minutes zero-padded to 2 digits: 0 -> `"0:00"`, 5 -> `"0:05"`, 90 -> `"1:30"`, 1500 -> `"25:00"`.

## Context

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/model/Minutes.kt` (lines 1-19, the whole file):

```kotlin
package io.github.jcszymansk.simpletracker.core.model

import io.github.jcszymansk.simpletracker.core.AppError
import io.github.jcszymansk.simpletracker.core.Outcome

/** A non-negative whole number of minutes. */
@JvmInline
value class Minutes private constructor(val value: Long) {
    companion object {
        val ZERO: Minutes = Minutes(0)

        fun of(value: Long): Outcome<Minutes> =
            if (value < 0) {
                Outcome.Err(AppError.InvalidTime(value.toString()))
            } else {
                Outcome.Ok(Minutes(value))
            }
    }
}
```

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/Outcome.kt` (lines 7-10):

```kotlin
sealed interface Outcome<out T> {
    data class Ok<out T>(val value: T) : Outcome<T>
    data class Err(val error: AppError) : Outcome<Nothing>
}
```

`core/src/commonMain/kotlin/io/github/jcszymansk/simpletracker/core/AppError.kt` (line 24 is the error to use):

```kotlin
    data class InvalidTime(val raw: String) : AppError
```

Existing test style, `core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/model/MinutesTest.kt` (lines 1-32): package `...core.model`, imports `kotlin.test.Test`, `assertEquals`, `assertIs`, `AppError`, `Outcome`; test names are backticked sentences; results are checked with `assertIs<Outcome.Ok<Minutes>>(Minutes.of(90))` and `assertEquals(Outcome.Err(AppError.InvalidTime("-1")), Minutes.of(-1))`. The file ends with a test `ZERO is zero minutes` (lines 28-31) and the class closes at line 32.

The `core` module is Kotlin Multiplatform with `allWarningsAsErrors = true`, so an unused import or variable fails the build. Code in `commonMain` must not import `java.*` or `javax.*` (a portability test enforces it); `Regex` and `String.padStart` are fine.

## Steps

1. Write `TimeInputTest.kt` in `core/src/commonTest/kotlin/io/github/jcszymansk/simpletracker/core/model/` first, class `TimeInputTest`, with these tests:
   - parses the example table from Interfaces (check the numeric `.value.value`);
   - rejects every malformed example from Interfaces, asserting `Outcome.Err(AppError.InvalidTime(raw))`;
   - keeps the raw, untrimmed text in the error for `" 1:60 "`, `"  abc  "` and `"\t1:5"`;
   - formats 0, 5, 90 and 1500 as listed;
   - format then parse round trips for 0, 5, 59, 60, 90, 1500 and 599_999;
   - every value from 0 through 599_999 round trips (a plain loop over the range).
   Use two private helpers, one that parses and unwraps with `assertIs<Outcome.Ok<Minutes>>`, one that builds a `Minutes` via `Minutes.of` and formats it.
2. Add three tests to `MinutesTest.kt`: `Minutes.of(599_999)` is Ok with that value; `Minutes.of(600_000)` is `Outcome.Err(AppError.InvalidTime("600000"))`; `Minutes.MAX.value` is `599_999L`.
3. Run the first done_when command. It must fail to compile or fail (there is no `TimeInput` or `Minutes.MAX` yet). Do not continue until you have seen it fail.
4. In `Minutes.kt` add `val MAX: Minutes = Minutes(599_999)` with a doc comment, change `of` to accept only `value in 0..MAX.value`, and update the class doc comment to say the range is zero through 9999:59 and that every value round trips through `TimeInput`.
5. Create `TimeInput.kt`: a private `Regex("^([0-9]{1,4}):([0-5][0-9])$")`; `parse` matches `raw.trim()` with `matchEntire`, returns `Outcome.Err(AppError.InvalidTime(raw))` on no match, otherwise computes `hours * 60 + minutes` as `Long` and returns `Minutes.of(...)`; `format` returns `"$hours:${remainder.toString().padStart(2, '0')}"` from `minutes.value / 60` and `minutes.value % 60`. Add a KDoc to the object stating the format.
6. Run both done_when commands in order; both must exit 0. The second runs the whole `core` test suite, including the portability scan, so keep `commonMain` free of platform imports.

## Out of scope

- Do not touch any file outside `files`. `EntryDraft`, the codec, the repository and the desktop module do not exist in this form yet or must not change; no other call site needs updating because `Minutes.of` keeps its signature.
- Do not change the existing three tests in `MinutesTest.kt`.
- If the build fails for a reason unrelated to these files (toolchain, network, an unrelated failing test at the start), stop and report it as a blocker with the command and its last 20 lines of output instead of working around it.
