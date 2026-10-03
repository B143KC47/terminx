# Adversarial review

## Outcome

The objective is a reviewable Windows release with readable source, controlled startup, documentation, tests, and complete installation assets.
The primary review mode is critique.
The secondary mode is release planning.

## Claim ledger

| Class | Finding | Evidence or resolution |
|---|---|---|
| Fact | The initial source tree had unpublished sidebar work | Git status and source review |
| Fact | One of 103 baseline tests failed | Native timestamp rounding discarded a completion event |
| Fact | Python and package versions disagreed | One source version now controls the package |
| Fact | Frozen helper calls could not use Python module commands | Fixed helper dispatcher and package checks |
| Constraint | The sidebar targets the current Windows user | No administrator or system service requirement |
| Assumption | Successful compilation proves installation behavior | Rejected; installation and removal need different checks |
| Assumption | A skipped desktop test means the desktop dependency is absent | Rejected; DLL import failures now stop the suite |
| Unknown | Every future provider version keeps these event formats | Provider fixtures and explicit unknown state limit the claim |
| Unknown | Automatic prose checks prove all ASD-STE100 rules | They check a subset; full compliance needs different review |

## Counterexamples and corrections

| Severity | Counterexample | Correction |
|---|---|---|
| High | A frozen GUI runs itself with `-m` and fails to start a helper | Use the console EXE and a fixed helper module list |
| High | A package injects Qt DLL paths into an external provider CLI | Remove package environment paths and restore the DLL search path |
| High | A second Python installation supplies an incompatible ICU DLL during packaging | Use a controlled build PATH and validate every binary origin |
| High | A valid completion timestamp rounds below the saved datetime | Compare both event times at datetime precision |
| High | A log record larger than the read limit blocks all later events | Skip oversized records across bounded reads |
| High | A command client exits before the sidebar reads its close message | Keep the connection open until the server confirms receipt |
| High | A disabled startup option becomes enabled during an update | Read current Windows startup state before installation |
| Medium | A null path map or invalid refresh interval crashes collection | Validate field types and numeric limits without replacing the file |
| Medium | An import failure causes all desktop tests to skip | Skip only a missing PySide6 module |
| Medium | Package removal leaves hooks pointing at a removed EXE | Remove recorded termiX hooks before program removal |
| Medium | A distribution contains no upstream license notices | Copy original notices and include the component record |
| Low | Dense statements and inconsistent imports hide behavior | Apply one format and import rules to source and tests |

## Readability review

The provider, monitor, event, quota, terminal, and interface boundaries stay explicit.
The review replaces inline helper code with named modules.
The review separates startup settings from display state.
The review applies one statement per line and a checked formatter.
Large widget construction methods stay in the sidebar.
They are a maintenance cost, but unrelated structural changes would increase release risk.

## Validation record

The maintained validation record is [Windows validation](sidebar-validation.md).
The local suite passed 131 tests without skipped desktop tests.
The measured statement coverage was 63.14 percent.
Startup coverage was 100 percent; event reduction coverage was 93 percent.
Log reader coverage was 89 percent; hook configuration coverage was 92 percent.
Code, document, and dependency checks passed.
The dependency check found no known vulnerabilities in the locked environment.
Native focus checks passed nine marker scenarios and seven existing terminal scenarios.
Native control checks passed seven interaction scenarios.
Visual checks passed at scale factors 1.0, 1.5, 1.875, and 2.0.
The real package check passed installation, startup controls, update settings, removal, and note preservation.
The local communication tests use different processes and incomplete message frames.
The published acceptance record contains Boolean results for these package checks.
One early native run missed a panel click.
A later serialized run passed all seven checks.
We did not establish the cause of that early miss.
Unit coverage measures executed source statements.
It does not measure the accuracy of every provider or native terminal layout.
The project uses native probe checks for the operating system boundary.

## Strongest objection

Mocked tests and a compiled installer can both pass while the installed application fails.
The release therefore needs an extracted portable run and real installation, startup, update, and removal checks.
A full machine reboot stays a different acceptance condition.
Current startup verification checks the actual Windows command and its execution.

## Reversibility and residual risk

The startup setting changes one current user registry value.
Hook removal keeps unrelated hooks and later user edits.
Package removal keeps notes.
Future provider schema changes can still require an adapter update.
Protected terminal layouts can still prevent verified focus.
The application reports these limits instead of claiming success.
