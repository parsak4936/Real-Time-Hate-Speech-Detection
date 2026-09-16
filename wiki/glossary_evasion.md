# Glossary — Evasion and Obfuscation

Spelling and formatting tricks used to slip a slur or attack past a filter while
keeping it readable to humans. A moderation model should normalise past these before
judging.

## Common tactics

- **Leetspeak / number substitution** — swapping letters for digits or symbols
  (a→4, e→3, i→1, o→0, s→5). The word is still legible when read aloud.
- **Character insertion and spacing** — extra dots, dashes, spaces, or zero-width
  characters inside a slur to break exact-match filters (for example "s l u r" or
  "s.l.u.r").
- **Homoglyphs** — visually identical letters from other alphabets (Cyrillic "а" for
  Latin "a"), so the string looks normal but is not.
- **Repetition and padding** — stretching or padding a word so a naive filter
  tokenises it differently.
- **Partial masking with intent** — self-censoring a slur ("the n-word") is usually
  not an attack; deliberately obfuscating it to aim it at someone still is.

## How to read them

De-obfuscate first, then apply policy_core. Recovering the intended word does not
by itself make the message hateful — check whether the recovered content is aimed at
a person or group. Someone naming an evasion tactic to report it is not committing
one.
