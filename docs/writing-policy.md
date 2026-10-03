# Writing policy

## Reference and scope

Use [ASD-STE100 Issue 9](https://asd-ste100.org/STE_downloads.html) for maintained English project documentation.
The reference issue date is 2025-01-15.
The scope includes root manuals, guides, source docstrings, issue forms, and pull request text.
The project has one English manual set.
Chinese interface text is a translation resource, not an English manual.
Original third-party licenses and the MIT license keep their legal wording.
Commands, paths, API fields, and code examples keep their exact identifiers.

## Writing rules

1. Use approved dictionary words with their approved meanings and parts of speech.
2. Use defined technical nouns and technical verbs when the subject requires them.
3. Use the same term for the same item.
4. Write instructions in the imperative form.
5. Give one action in each instruction sentence.
6. Put a condition before its related action.
7. Use active voice.
8. Keep each project sentence at 20 words or fewer.
9. Use short paragraphs with one subject.
10. Define an abbreviation before use in prose.
11. Use complete references to files and controls.
12. Keep instructions out of notes.

The project limit of 20 words also applies to descriptive sentences.
The standard permits up to 25 words in descriptive sentences.
The project uses the smaller limit to simplify checks.

## Project terms

See the [technical term list](terms.md).
Technical nouns identify software, computer components, data items, and product controls.
Technical verbs identify software and interface operations.
Product names and exact interface labels retain their official spelling.
Do not use a technical term to permit an unrelated ordinary word.

## Review procedure

1. Check the procedure against the current application behavior.
2. Check the selected word meanings in the official dictionary.
3. Check the part of speech for each approved word.
4. Check the technical terms against the project list.
5. Check instructions, conditions, voice, and paragraph subjects.
6. Run `python scripts/check_docs.py`.
7. Record any remaining exception in the review record.

The script checks sentence length, English prose, contractions, and selected excluded words.
It also checks source docstrings.
It does not prove all dictionary meanings, parts of speech, or grammatical rules.
A qualified author can perform an independent full compliance review.
The project does not claim official certification.
