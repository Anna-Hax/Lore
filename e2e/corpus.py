"""Illustrative research notes for the end-to-end run and the showcase.

Written for this demo: plausible "what worked / what didn't" notes, not real experimental results.
Each is above MIN_CHARS. `tag` makes a run's texts unique (the contract refuses an exact contentHash twice).
"""

FINETUNE_ROOT = """Dead ends in LoRA fine-tuning of 1B-3B models for structured extraction.
We fine-tuned three open 1B-3B base models to extract invoice fields into JSON, sweeping LoRA rank over 4, 8, 16, 32 and 64.
Exact-match F1 rose from rank 4 to rank 16 and then stayed flat within noise; rank 64 started to overfit after the second epoch,
with validation loss rising while training loss kept falling. The alpha-to-rank ratio mattered more than rank itself:
keeping alpha at twice the rank was stable, while a fixed alpha of 16 made high ranks learn too slowly.
Dead end one: adapting only the attention projections. Adding the MLP projections gave the largest single gain (about 7 F1 points),
far more than any rank change. Dead end two: training on 30k synthetic invoices alone. Models learned the generator's layout quirks
and lost about 11 points on real scanned invoices; mixing in 2k real documents recovered most of it.
Dead end three: very long sequence packing, which hurt field ordering. Save your compute: rank 16, alpha 32, all linear layers,
2 epochs, and at least some real data."""

FINETUNE_COPYCAT = """Dead ends in LoRA fine-tuning of 1B-3B models for structured extraction tasks.
We fine-tuned three open 1B-3B base models to extract invoice fields into JSON, sweeping LoRA rank over 4, 8, 16, 32 and 64.
Exact-match F1 rose from rank 4 to rank 16 and then stayed flat within noise; rank 64 began to overfit after the second epoch,
with validation loss rising while training loss kept falling. The alpha-to-rank ratio mattered more than the rank itself:
keeping alpha at twice the rank was stable, while a fixed alpha of 16 made high ranks learn too slowly.
Dead end one: adapting only the attention projections. Adding the MLP projections gave the largest single gain (about 7 F1 points),
far more than any rank change. Dead end two: training on 30k synthetic invoices alone. Models learned the generator's layout quirks
and lost about 11 points on real scanned invoices; mixing in 2k real documents recovered most of it.
Dead end three: very long sequence packing, which hurt field ordering. Save your compute: use rank 16, alpha 32, all linear layers,
2 epochs, and at least some real data."""

FINETUNE_MIXING = """Learning-rate schedules and data mixing when fine-tuning small models: negative results.
Building on rank-16 LoRA adapters across all linear layers for extraction, we tested whether the schedule or the data mix
explains the remaining gap. Cosine decay versus a constant learning rate made no measurable difference after the second epoch;
warmup longer than 3 percent of steps only slowed convergence. What did matter was forgetting: after extraction fine-tuning,
the models lost about 9 points on a general instruction-following check. Mixing 10 percent general instruction data into every
batch removed almost all of that loss while costing under 1 point of extraction F1. Dead end: curriculum ordering by document
length, short to long, which was consistently worse than random order and made the model truncate long line-item tables.
Dead end: freezing the embedding layer to save memory, which hurt rare currency and tax codes. Recommendation: constant or cosine,
short warmup, 10 percent general data, random order, and keep embeddings trainable when the target vocabulary is unusual."""

FINETUNE_EVAL = """Benchmark contamination from paraphrased synthetic data in small-model fine-tuning.
When we re-checked the extraction benchmark used to compare adapter settings, 14 percent of test items had close paraphrases
in the synthetic training set: the generator had been seeded from public invoice templates that the benchmark also used.
Exact and 13-gram deduplication found almost none of them because field values were reshuffled. Embedding-based deduplication
with a cosine threshold of 0.9 on whole documents caught 93 percent of the overlap in a manual audit of 300 pairs.
After removing contaminated items, every configuration dropped about 6 F1 points, but the ranking of configurations did not change,
so earlier conclusions about rank, mixing and schedules still hold. Dead end: deduplicating at the field level, which flagged
thousands of harmless shared values such as country names. Practical rule: deduplicate synthetic training data against the
benchmark with document-level embeddings before trusting any small-model comparison."""

RAG_ROOT = """Chunk size and chunking strategy for retrieval-augmented QA over internal docs: what did not help.
We swept fixed chunk sizes of 128, 256, 512, 1024 and 2048 tokens over a 40k-page engineering wiki, with 50 to 64 token overlap,
and scored answer correctness on 600 human-written questions. 512-token chunks with 64-token overlap were best overall;
128 and 256 lost context for multi-step answers, and 2048 diluted retrieval so the right passage often ranked below 10.
Dead end one: semantic chunking by embedding breakpoints. It cost 4x more to index and matched fixed 512-token chunks within noise.
Dead end two: sentence-window retrieval, which helped short factual questions but hurt procedures spread across a page.
Dead end three: adding page titles to every chunk, which only helped when titles were descriptive, which they mostly were not.
Start with fixed 512-token chunks and 64 overlap, and spend effort on retrieval and reranking instead."""

RAG_RERANK = """Reranking and hybrid retrieval on top of fixed 512-token chunks: results and dead ends.
On the same 600-question set, dense retrieval alone reached 71 percent recall at 5. Adding BM25 in a hybrid with reciprocal rank
fusion raised it to 79 percent, almost entirely from questions with acronyms, error codes and product names that embeddings blur.
A cross-encoder reranker over the top 50 added another 9 points of recall at 5 and 6 points of answer correctness, at about
120 ms extra latency per query on one GPU. Dead end one: LLM query expansion, which rewrote precise error codes into vague
paraphrases and cut precision by 5 points. Dead end two: retrieving 20 chunks into the prompt, which made answers worse than
retrieving 6 well-reranked ones. Dead end three: fine-tuning the embedding model on 2k pairs, which gained 2 points and was not
worth the maintenance. Use hybrid BM25 plus dense, rerank the top 50, and pass 5 or 6 chunks."""


def tagged(text: str, tag: str | None) -> str:
    return text if not tag else f"{text}\nLab note {tag}."
