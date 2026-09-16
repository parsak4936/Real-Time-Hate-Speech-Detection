# Moderation Knowledge Base — Index

This is the curated knowledge base consulted by the LLM-Wiki backend. Unlike the
RAG backend (which retrieves similar past cases), the pages here hold *rules and
definitions*: what the labels mean, how strictness shifts by domain, the coded
language and evasion tactics to watch for, and the edge cases where the obvious
reading is wrong.

## Pages

- **policy_core** — the three labels (HATE / OFFENSIVE / NORMAL), intent vs impact,
  protected characteristics, and the general decision principles.
- **domain_gaming** — low-strictness rules for gaming and esports chat.
- **domain_politics_news** — high-strictness rules for political and news content.
- **domain_reviews** — medium-strictness rules for consumer-review platforms.
- **domain_general** — default rules when the domain is unclear.
- **glossary_dogwhistles** — coded language and symbols that carry hateful meaning.
- **glossary_evasion** — spelling tricks used to slip slurs past filters.
- **edge_cases** — reclaimed slurs, sarcasm, quoting-not-endorsing, and other traps.

## How to use it

Always read policy_core first, then the page for the message's domain, then any
glossary or edge-case entry that matches the message. The knowledge base guides the
decision; the literal content of the message still governs the final call.
