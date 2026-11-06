+++
schema = "lite.card.v1"
id = "cal-st-import-token-scan"
kind = "bugfix"
files = [
  "core/src/jvmTest/kotlin/io/github/jcszymansk/simpletracker/core/architecture/CommonMainImportScanner.kt",
  "core/src/jvmTest/kotlin/io/github/jcszymansk/simpletracker/core/architecture/CommonMainPortabilityTest.kt",
]
done_when = [
  "nix develop --command ./gradlew :core:jvmTest --tests 'io.github.jcszymansk.simpletracker.core.architecture.CommonMainPortabilityTest'",
  "nix develop --command ./gradlew :core:jvmTest",
]
+++

## Goal

The test helper that scans Kotlin sources for forbidden platform imports finds an import directive by tokens, not by line prefix. A forbidden import is reported even when comments or line breaks sit between `import`, the path segments and an `as` alias, and `import` text inside comments or string literals is never reported.

## Interfaces

No public signature changes. In `CommonMainImportScanner.kt` (package `io.github.jcszymansk.simpletracker.core.architecture`, test source set) these stay as they are:

```kotlin
internal val FORBIDDEN_IMPORT_PREFIXES: List<String>
internal sealed interface ImportScanResult {
    data class Clean(val fileCount: Int) : ImportScanResult
    data class Violations(val fileCount: Int, val lines: List<String>) : ImportScanResult
    data object NoSources : ImportScanResult
}
internal fun scanImports(root: Path, forbiddenPrefixes: List<String> = FORBIDDEN_IMPORT_PREFIXES): ImportScanResult
```

Add file-private helpers of your own choosing (a tokenizer and an import reader). What is fixed is the observable result. Each `Violations.lines` entry is

```
<file name>:<line of the 'import' keyword>: import <normalised path>
```

where the normalised path is the dotted path with single dots and no whitespace or comments, `.*` for a star import, and ` as <alias>` appended when there is an alias. The prefix check (`forbiddenPrefixes.any { path.startsWith(it) }`) is applied to that normalised path. Examples:
- `"import /* comment */ java.io.File"` on line 3 gives `Commented.kt:3: import java.io.File`;
- `"import java\n    .io /* package */\n    .File as F"` starting on line 3 gives `Split.kt:3: import java.io.File as F`.

## Context

`core/src/jvmTest/kotlin/io/github/jcszymansk/simpletracker/core/architecture/CommonMainImportScanner.kt`, lines 1-45 (the whole file; the buggy part is lines 29-39):

```kotlin
package io.github.jcszymansk.simpletracker.core.architecture

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.extension
import kotlin.io.path.isRegularFile

internal val FORBIDDEN_IMPORT_PREFIXES = listOf("java.", "javax.", "android.", "androidx.", "sun.")

internal sealed interface ImportScanResult {
    data class Clean(val fileCount: Int) : ImportScanResult
    data class Violations(val fileCount: Int, val lines: List<String>) : ImportScanResult
    data object NoSources : ImportScanResult
}

internal fun scanImports(
    root: Path,
    forbiddenPrefixes: List<String> = FORBIDDEN_IMPORT_PREFIXES,
): ImportScanResult {
    if (!Files.isDirectory(root)) {
        return ImportScanResult.NoSources
    }
    val files = Files.walk(root).use { stream ->
        stream.filter { it.isRegularFile() && it.extension == "kt" }.toList()
    }
    if (files.isEmpty()) {
        return ImportScanResult.NoSources
    }
    val violations = files.flatMap { file ->
        Files.readAllLines(file).withIndex().mapNotNull { (index, line) ->
            val trimmed = line.trim()
            val imported = trimmed.removePrefix("import ").trim()
            if (trimmed.startsWith("import ") && forbiddenPrefixes.any { imported.startsWith(it) }) {
                "${file.fileName}:${index + 1}: $trimmed"
            } else {
                null
            }
        }
    }
    return if (violations.isEmpty()) {
        ImportScanResult.Clean(files.size)
    } else {
        ImportScanResult.Violations(files.size, violations)
    }
}
```

Why it is wrong: the line check only sees `import ` at the start of a trimmed line, so `import /* x */ java.io.File` or a path split over lines is invisible to it.

`core/src/jvmTest/kotlin/io/github/jcszymansk/simpletracker/core/architecture/CommonMainPortabilityTest.kt` (lines 1-85): imports `java.nio.file.Files`, `java.nio.file.Path`, `kotlin.io.path.writeText`, `kotlin.test.AfterTest/Test/assertEquals/assertTrue/fail`. Tests write a file into a temp directory with `val root = newTempDirectory()` then `root.resolve("Bad.kt").writeText("...")`, call `scanImports(root)` and check the result, e.g. lines 71-81:

```kotlin
    @Test
    fun `aliased forbidden imports are reported`() {
        val root = newTempDirectory()
        root.resolve("Aliased.kt").writeText("package bad\n\nimport javax.swing.JFrame as Frame\n")

        val result = scanImports(root)

        val violations = result as? ImportScanResult.Violations
            ?: fail("expected violations, got $result")
        assertTrue(violations.lines.single().contains("javax.swing.JFrame"), violations.lines.single())
    }
```

`newTempDirectory()` is the private helper at lines 83-84 and the class closes at line 85. The first test (lines 24-36) runs the scan over the real `core/src/commonMain/kotlin` tree, so the new scanner must also report that tree as clean.

Kotlin lexical facts the scanner must respect: line comments `// ...`; block comments `/* ... */` that nest; string literals `"..."` with backslash escapes; raw strings `"""..."""`; char literals `'x'` with backslash escapes; identifiers may be quoted with backticks.

The `core` module compiles with `allWarningsAsErrors = true`; no unused variables or imports.

## Steps

1. In `CommonMainPortabilityTest.kt` add four tests after `aliased forbidden imports are reported` (each writes one file into `newTempDirectory()` and calls `scanImports`):
   - `comments between import tokens are reported`: file `Commented.kt` with content `"package bad\n\nimport /* comment */ java.io.File\n"`; expect `Violations` whose `lines` equal `listOf("Commented.kt:3: import java.io.File")`;
   - `comments and line breaks inside the import path are reported`: file `Split.kt` with content `"package bad\n\nimport java\n    .io /* package */\n    .File as F\n"`; expect `lines == listOf("Split.kt:3: import java.io.File as F")`;
   - `commented out imports are ignored`: file `Commented.kt` with `"package good\n\n// import java.io.File\n/* import javax.swing.JFrame */\nclass Good\n"`; expect `ImportScanResult.Clean(1)`;
   - `imports mentioned in strings are ignored`: file `Text.kt` with `"package good\n\nval text = \"import java.io.File\"\n"`; expect `ImportScanResult.Clean(1)`.
2. Run the first done_when command and confirm it fails. The two "reported" tests fail on the old scanner; the "ignored" tests may already pass, which is fine.
3. Replace the line-based loop in `scanImports` with: read the whole file with `Files.readString(file)`, turn it into tokens (identifier with a flag for backtick-quoted, dot, star; each token carries its 1-based line number), then walk the tokens looking for an unquoted identifier `import` followed by an identifier. From there read `ident (. ident)* (. *)?` and an optional unquoted `as ident`, building the normalised path. The tokenizer must skip whitespace and the comment, string, raw string and char literal forms listed above while still counting newlines inside them, so line numbers stay right. Then keep the directives whose path starts with a forbidden prefix and format each as `"${file.fileName}:${directive.line}: import ${directive.path}"`.
4. Keep the result type and the `Clean`/`Violations`/`NoSources` logic unchanged. Add a KDoc to the import finder that says imports are matched on tokens so comments and whitespace cannot hide one.
5. Run both done_when commands; both must exit 0. The second includes the scan of the real `commonMain` tree.

## Out of scope

- Do not change `FORBIDDEN_IMPORT_PREFIXES`, `ImportScanResult`, or the `core/build.gradle.kts` system property that points the test at `commonMain`.
- Do not edit any file under `commonMain` to make the scan pass; if the real tree is reported dirty, that is a finding to report, not something to fix here.
- Do not add a dependency (no Kotlin parser library); a small hand-written tokenizer is the intended solution.
- If the existing tests fail before you change anything, or the toolchain cannot run, stop and report a blocker with the command and the last 20 lines of output.
