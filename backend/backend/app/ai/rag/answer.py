"""Evidence-based answers with citations, plus the Self-RAG style checks that keep them honest.

* extractive_answer  picks the best sentences from the retrieved passages and cites each one [n]; every sentence is a
                     verbatim quote, so it cannot invent facts.
* llm_answer         asks a language model to write from the numbered passages only, then verifies it. Unsupported
                     sentences are removed; if too little survives the extractive answer is used instead.
* verify             support score per sentence (how much of it is found in the cited passage) and citation validity.
* numbers_grounded   every number in an answer must come from the evidence or from a tool result (Python / ML / solver),
                     never from the language model's imagination."""
from __future__ import annotations

import re

from ...services.rag_hybrid import expand, stem, tokens

CITE = re.compile(r"\[(\d+)\]")
NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?:\s?%)?")


def cite_sentence(sentence: str, n: int) -> str:
    """'It is locked.' + 1 -> 'It is locked [1].' (the citation sits inside the sentence)."""
    s = sentence.strip()
    end = s[-1] if s and s[-1] in ".!?" else ""
    return f"{s[:-1] if end else s} [{n}]{end}"


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").replace("\n", " ")) if len(s.strip()) > 12]


def extractive_answer(question: str, evidence: list[dict], max_sentences: int = 4) -> dict:
    q_terms = expand(tokens(question))
    cand = []
    for ev in evidence:
        for pos, s in enumerate(split_sentences(ev["text"])):
            toks = set(tokens(s))
            overlap = sum(w for t, w in q_terms.items() if t in toks)
            if overlap <= 0:
                continue
            # prefer sentences that cover many query terms, early in the passage, from the strongest evidence
            cand.append((overlap / (1 + 0.15 * pos) * (0.6 + 0.4 * ev.get("confidence", 0.5)), ev["n"], s))
    cand.sort(key=lambda c: -c[0])
    chosen, seen_text = [], set()
    for score, n, s in cand:
        if s in seen_text:
            continue
        chosen.append((n, s))
        seen_text.add(s)
        if len(chosen) >= max_sentences:
            break
    chosen.sort(key=lambda c: (c[0], evidence_pos(evidence, c[0], c[1])))
    text = " ".join(cite_sentence(s, n) for n, s in chosen)
    return {"text": text, "sentences": [{"text": s, "cites": [n]} for n, s in chosen]}


def evidence_pos(evidence: list[dict], n: int, sentence: str) -> int:
    for ev in evidence:
        if ev["n"] == n:
            return ev["text"].find(sentence)
    return 0


def verify(answer_text: str, evidence: list[dict], min_support: float = 0.6) -> dict:
    by_n = {ev["n"]: ev for ev in evidence}
    sentences, bad_cites = [], []
    answer_text = re.sub(r"([.!?])\s+(\[\d+\])", r" \2\1", answer_text)   # a citation after the full stop still belongs to its sentence
    for s in split_sentences(answer_text):
        cites = [int(c) for c in CITE.findall(s)]
        body = re.sub(r"^\d+\)\s*", "", re.sub(r"\s+([.,;!?])", r"\1", CITE.sub("", s).strip()))   # "2) ..." is a list marker, not a claim
        for c in cites:
            if c not in by_n:
                bad_cites.append(c)
        toks = set(tokens(body))
        support = 0.0
        pool = [by_n[c] for c in cites if c in by_n] or evidence
        for ev in pool:
            have = set(tokens(ev["text"]))
            if toks:
                support = max(support, len(toks & have) / len(toks))
        # a sentence that states a number the cited passage does not contain is unsupported, however many words match
        pool_numbers = {n.replace(",", "").replace("%", "").strip() for ev in pool for n in NUM.findall(ev["text"])}
        if any(n.replace(",", "").replace("%", "").strip() not in pool_numbers for n in NUM.findall(body)):
            support = min(support, 0.3)
        sentences.append({"text": body, "cites": cites, "support": round(support, 3), "supported": bool(cites) and support >= min_support and not any(c not in by_n for c in cites)})
    ok = bool(sentences) and all(x["supported"] for x in sentences)
    return {"ok": ok, "sentences": sentences, "invalid_citations": sorted(set(bad_cites)),
            "unsupported": [x["text"] for x in sentences if not x["supported"]]}


def numbers_grounded(answer_text: str, evidence_texts: list[str], allowed: list[float] | None = None) -> dict:
    """Numbers in the answer that appear neither in the evidence nor among the values computed by tools."""
    def norm(x: str) -> str:
        return x.replace(",", "").replace("%", "").strip()

    known = {norm(n) for t in evidence_texts for n in NUM.findall(t)}
    for v in allowed or []:
        known |= {norm(f"{v:g}"), norm(f"{v:.0f}"), norm(f"{v:.1f}"), norm(f"{v:.2f}"), norm(f"{v * 100:.0f}")}
    clean = re.sub(r"(?m)(^|(?<=[.!?]\s))\d+\)\s", "", CITE.sub("", answer_text))   # drop "1) " list markers
    stray = [n for n in NUM.findall(clean) if norm(n) not in known]
    return {"ok": not stray, "ungrounded": stray}


def build_prompt(question: str, evidence: list[dict]) -> str:
    blocks = "\n\n".join(f"[{e['n']}] {e['title']} ({e['source']})\n{e['text']}" for e in evidence)
    return ("Answer the question using ONLY the numbered passages. After every sentence add the passage number in square brackets, "
            "for example [2]. If the passages do not contain the answer, reply exactly: INSUFFICIENT EVIDENCE.\n\n"
            f"Question: {question}\n\nPassages:\n{blocks}")


def llm_answer(question: str, evidence: list[dict], llm) -> dict:
    """`llm(prompt) -> str`. Returns the verified answer, or the extractive fallback when the model is unsupported or fails."""
    fallback = extractive_answer(question, evidence)
    try:
        raw = (llm(build_prompt(question, evidence)) or "").strip()
    except Exception:
        return {**fallback, "mode": "extractive_fallback", "reason": "language model unavailable"}
    if not raw or "INSUFFICIENT EVIDENCE" in raw:
        return {**fallback, "mode": "extractive_fallback", "reason": "model reported insufficient evidence"}
    check = verify(raw, evidence)
    kept = [s for s in check["sentences"] if s["supported"]]
    if check["invalid_citations"] or len(kept) < max(1, len(check["sentences"]) // 2):
        return {**fallback, "mode": "extractive_fallback", "reason": "model answer was not supported by the passages"}
    text = " ".join(cite_sentence(s["text"], s["cites"][0]) if s["cites"] else s["text"] for s in kept)
    return {"text": text.strip(), "sentences": [{"text": s["text"], "cites": s["cites"]} for s in kept], "mode": "llm_verified",
            "dropped": [s["text"] for s in check["sentences"] if not s["supported"]]}
