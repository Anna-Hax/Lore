"""Deterministic v1 watermark. Removing zero-width characters removes it.

Payload: first 8 bytes of HMAC-SHA256(secret, address20 || utf8(ref)),
where ref is a canonical "node:<id>" or "sub:<id>" with a positive uint256 ID.
MSB first, U+200B = 0 and U+200C = 1, framed by U+2063. Framing lets scoring
ignore incomplete marks at excerpt boundaries instead of losing bit alignment.
"""

import hashlib
import hmac
import re
from bisect import bisect_right

from ._secrets import secret_bytes

ZERO, ONE, FRAME = "\u200b", "\u200c", "\u2063"
_MARK = re.compile(FRAME + f"([{ZERO}{ONE}]{{64}})" + FRAME)
_SENTENCE_END = re.compile(r'''(?:[。！？]+["'”’»\)\]]*|[.!?]+["'”’»\)\]]*(?=\s|$))''')
_TICKS = re.compile(r"(?<!`)(`+)(?!`)")


def validate_plaintext(text: str) -> None:
    """Reject reserved marking characters before ingest and before delivery.

    P1 should map ValueError to a client error at /ingest, before encrypting or
    uploading. Reject rather than silently changing hashed research. This also
    refuses already-watermarked copies; marks must never stack across buyers.
    """
    if not isinstance(text, str):
        raise ValueError("plaintext must be a string")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("plaintext must be valid UTF-8") from None
    if any(character in text for character in (ZERO, ONE, FRAME)):
        raise ValueError("plaintext contains reserved watermark characters")


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Protect ordinary Markdown backtick spans and backtick/tilde fences.

    Conservative, small scanner; not a general Markdown parser. An unclosed
    fence protects the rest of the document. Code-only excerpts have no marks.
    """
    fences = []
    opening = None
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if opening is not None:
            start, symbol, length = opening
            if re.fullmatch(rf" {{0,3}}{re.escape(symbol)}{{{length},}}[ \t]*", body):
                fences.append((start, offset + len(line)))
                opening = None
        else:
            match = re.match(r" {0,3}(`{3,}|~{3,})", body)
            if match:
                opening = (offset, match[1][0], len(match[1]))
        offset += len(line)
    if opening is not None:
        fences.append((opening[0], len(text)))

    spans = list(fences)
    # Scan inline code only in the gaps between fenced blocks.
    start = 0
    for end, after in [*fences, (len(text), len(text))]:
        cursor = start
        while match := _TICKS.search(text, cursor, end):
            closing = re.compile(r"(?<!`)" + re.escape(match[1]) + r"(?!`)").search(text, match.end(), end)
            if closing is None:
                cursor = match.end()
                continue
            finish = closing.end()
            spans.append((match.start(), finish))
            cursor = finish
        start = after
    return sorted(spans)


def normalize_wallet(wallet: str) -> str:
    if not isinstance(wallet, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", wallet):
        raise ValueError("wallet must be a 0x-prefixed 20-byte address")
    return wallet.lower()


def _payload(wallet: str, ref: str, wm_secret: bytes | None) -> str:
    address = bytes.fromhex(normalize_wallet(wallet)[2:])
    if not isinstance(ref, str) or not re.fullmatch(r"(?:node|sub):[1-9][0-9]{0,77}", ref):
        raise ValueError("ref must be node:<id> or sub:<id> with a canonical positive uint256 ID")
    if int(ref.split(":", 1)[1]) >= 2**256:
        raise ValueError("ref ID must fit in a uint256")
    digest = hmac.new(
        secret_bytes(wm_secret, "WM_SECRET"), address + ref.encode("utf-8"), hashlib.sha256
    ).digest()[:8]
    return "".join(ONE if byte & (1 << bit) else ZERO for byte in digest for bit in range(7, -1, -1))


def watermark(text: str, wallet: str, ref: str, *, wm_secret: bytes | None = None) -> str:
    validate_plaintext(text)
    mark = FRAME + _payload(wallet, ref, wm_secret) + FRAME
    protected = _code_spans(text)
    starts = [start for start, _ in protected]

    def outside_code(position: int) -> bool:
        # Check the last character before insertion. This conservatively avoids
        # marks immediately after inline code as well as inside code itself.
        index = bisect_right(starts, position - 1) - 1
        return index < 0 or position > protected[index][1]

    positions = {end.end() for end in _SENTENCE_END.finditer(text) if outside_code(end.end())}
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip()
        position = offset + len(body)
        # Line boundaries cover Markdown bullets and unpunctuated paragraphs.
        if body and outside_code(position):
            positions.add(position)
        offset += len(line)
    parts, offset = [], 0
    for position in sorted(positions):
        parts.extend((text[offset:position], mark))
        offset = position
    parts.append(text[offset:])
    return "".join(parts)


def score(leaked_text: str, wallet: str, ref: str, *, wm_secret: bytes | None = None) -> int:
    """Fraction of matching bits, in basis points; no complete marks means 0.

    This is a similarity score, not a confidence or proof of authorship. Wrong
    wallets average around 5000; callers must not treat any nonzero score as guilt.
    """
    expected = _payload(wallet, ref, wm_secret)
    marks = _MARK.findall(leaked_text)
    if not marks:
        return 0
    matches = sum(a == b for mark in marks for a, b in zip(mark, expected, strict=True))
    return matches * 10_000 // (64 * len(marks))
