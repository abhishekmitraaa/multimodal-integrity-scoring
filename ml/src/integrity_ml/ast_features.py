"""AST features (SPEC 6.3): tree-sitter Python, tolerant of syntax errors.

- Node histogram over the grammar's named node types plus ERROR, Laplace-smoothed.
- Problem-normalised ("tilted") distribution, student baseline, and histogram drift (JSD, base 2).
- Four scalar style features, z-scored per problem, and the style distance.
- AST jumps between consecutive snapshots: structure that arrived without typing.

AST drift is a weak signal, used only in fusion (SPEC 1, 6.3): with 2-3 practice problems the
baseline is noisy, and the problem dictates much of the structure. It is not a review flag on its
own. The parser and grammar are pinned in ml/pyproject.toml; grammar_info() records both.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from numpy.typing import NDArray

ERROR = "ERROR"
CONTROL_FLOW = frozenset({
    "if_statement", "for_statement", "while_statement", "try_statement", "with_statement",
    "match_statement", "function_definition", "lambda",
})

Event = Mapping[str, Any]


@lru_cache(maxsize=1)
def _language() -> Any:
    import tree_sitter
    import tree_sitter_python

    return tree_sitter.Language(tree_sitter_python.language())


@lru_cache(maxsize=1)
def vocabulary() -> tuple[str, ...]:
    """All visible named node types of the grammar, plus ERROR, sorted (the order of every vector)."""
    lang = _language()
    named = {lang.node_kind_for_id(i) for i in range(lang.node_kind_count)
             if lang.node_kind_is_named(i) and lang.node_kind_is_visible(i)}
    return tuple(sorted(named | {ERROR}))


@lru_cache(maxsize=1)
def _index() -> dict[str, int]:
    return {v: i for i, v in enumerate(vocabulary())}


def grammar_info() -> dict[str, Any]:
    """Versions and hashes to record with every result (SPEC 6.3, 14)."""
    import tree_sitter_python

    binding = sorted(Path(tree_sitter_python.__file__).parent.glob("_binding*"))
    return {
        "tree_sitter": importlib.metadata.version("tree-sitter"),
        "tree_sitter_python": importlib.metadata.version("tree-sitter-python"),
        "abi_version": int(_language().abi_version),
        "vocabulary_size": len(vocabulary()),
        "vocabulary_sha256": hashlib.sha256("\n".join(vocabulary()).encode()).hexdigest(),
        "grammar_binary_sha256": hashlib.sha256(binding[0].read_bytes()).hexdigest() if binding else None,
    }


# ---------------------------------------------------------------- one snapshot

@dataclass(frozen=True)
class AstSummary:
    counts: dict[str, int]                    # named node type -> count (ERROR included, MISSING nodes not)
    named_nodes: int
    error_nodes: int
    max_nesting: int                          # deepest chain of CONTROL_FLOW nodes
    mean_identifier_len: float | None         # over distinct identifier names
    short_identifier_frac: float | None       # distinct 1-character names / distinct names
    comment_frac: float                       # comment characters / all characters

    def style(self) -> NDArray[np.float64]:
        """The four scalar style features, NaN where undefined (no identifiers)."""
        return np.array([self.max_nesting,
                         np.nan if self.mean_identifier_len is None else self.mean_identifier_len,
                         np.nan if self.short_identifier_frac is None else self.short_identifier_frac,
                         self.comment_frac], dtype=np.float64)


STYLE_FEATURES = ("max_nesting", "mean_identifier_len", "short_identifier_frac", "comment_frac")


def summarize(code: str) -> AstSummary:
    import tree_sitter

    tree = tree_sitter.Parser(_language()).parse(code.encode("utf-8"))
    index = _index()
    counts: dict[str, int] = {}
    names: set[str] = set()
    comment_chars = 0
    max_nesting = 0
    stack: list[tuple[Any, int]] = [(tree.root_node, 0)]
    while stack:                               # iterative: deep nesting cannot exhaust the Python stack
        node, depth = stack.pop()
        if node.is_missing:                    # zero-width token the parser invented to recover
            continue
        kind = ERROR if node.is_error else node.type
        if not node.is_named:                  # keywords and punctuation (the "lambda" keyword is a token of type "lambda")
            continue
        if kind in index:
            counts[kind] = counts.get(kind, 0) + 1
        if kind in CONTROL_FLOW:
            depth += 1
            max_nesting = max(max_nesting, depth)
        if kind == "identifier":
            names.add(node.text.decode("utf-8", "replace"))
        elif kind == "comment":
            comment_chars += len(node.text.decode("utf-8", "replace"))
        stack.extend((child, depth) for child in node.children)
    return AstSummary(
        counts=counts,
        named_nodes=sum(counts.values()),
        error_nodes=counts.get(ERROR, 0),
        max_nesting=max_nesting,
        mean_identifier_len=float(np.mean([len(n) for n in names])) if names else None,
        short_identifier_frac=sum(1 for n in names if len(n) == 1) / len(names) if names else None,
        comment_frac=comment_chars / len(code) if code else 0.0,
    )


def available(summary: AstSummary, min_named_nodes: int) -> bool:
    return summary.named_nodes >= min_named_nodes


# ---------------------------------------------------------------- distributions and drift

def smoothed(counts: Mapping[str, int], alpha: float) -> NDArray[np.float64]:
    """P_s(v) = (h_s(v) + alpha) / (N + alpha |V|), over vocabulary() order."""
    if alpha <= 0:
        raise ValueError("alpha must be positive (the tilt divides by the reference)")
    h = np.zeros(len(vocabulary()), dtype=np.float64)
    index = _index()
    for kind, n in counts.items():
        h[index[kind]] += n
    return (h + alpha) / (h.sum() + alpha * len(h))


def reference(distributions: Sequence[NDArray[np.float64]]) -> NDArray[np.float64]:
    """R_p: the mean smoothed distribution over reference final solutions to one problem."""
    if not distributions:
        raise ValueError("a problem reference needs at least one solution")
    return np.mean(np.stack(distributions), axis=0)


def tilt(p: NDArray[np.float64], r: NDArray[np.float64]) -> NDArray[np.float64]:
    """Q_s ∝ P_s / R_p: removes what the problem dictates, keeps what the student adds."""
    q = p / r
    return q / q.sum()


def student_baseline(qs: Sequence[NDArray[np.float64]]) -> NDArray[np.float64]:
    """B_u: the normalised mean of the tilted distributions of the practice modules."""
    if not qs:
        raise ValueError("a baseline needs at least one practice module")
    b = np.mean(np.stack(qs), axis=0)
    return b / b.sum()


def jsd(p: NDArray[np.float64], q: NDArray[np.float64], base: float = 2.0) -> float:
    """Jensen-Shannon divergence; in [0, 1] with base 2. Zero entries contribute nothing."""
    m = (p + q) / 2

    def kl(a: NDArray[np.float64]) -> float:
        nz = a > 0
        return float(np.sum(a[nz] * np.log(a[nz] / m[nz])))

    return float(np.clip((kl(p) + kl(q)) / 2 / np.log(base), 0.0, 1.0))


def style_z(style: NDArray[np.float64], mean: NDArray[np.float64], sd: NDArray[np.float64]) -> NDArray[np.float64]:
    """z-scores against the per-problem population; NaN where the SD is 0 or a value is missing."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, (style - mean) / sd, np.nan)


def style_distance(z_exam: NDArray[np.float64], z_practice: Sequence[NDArray[np.float64]]) -> float | None:
    """d_ast,s = mean_k |z_exam,k - z_base,k|, z_base the mean over practice modules; None if no k is defined."""
    if not z_practice:
        return None
    with np.errstate(invalid="ignore"):
        stacked = np.stack(z_practice)
        counts = np.sum(~np.isnan(stacked), axis=0)
        z_base = np.where(counts > 0, np.nansum(stacked, axis=0) / np.maximum(counts, 1), np.nan)
    diff = np.abs(z_exam - z_base)
    ok = ~np.isnan(diff)
    return float(diff[ok].mean()) if ok.any() else None


# ---------------------------------------------------------------- AST jumps over a session

@dataclass(frozen=True)
class AstJump:
    t: float                  # seconds, client clock
    added_nodes: int
    keydowns: int             # editor keydowns since the previous snapshot
    reason: str               # the snapshot's reason (large_insert, timer, run, ...)


@dataclass(frozen=True)
class AstTimeline:
    jumps: list[AstJump]
    snapshots: int            # snapshots parsed
    truncated: bool           # more snapshots than max_snapshots: the rest were not checked
    final: AstSummary | None  # the last snapshot parsed


def ast_timeline(events: Sequence[Event], min_nodes: int, max_keydowns: int, max_snapshots: int,
                 max_chars: int) -> AstTimeline:
    """AST jumps (SPEC 6.3): between consecutive snapshots, at least min_nodes named nodes appear
    while fewer than max_keydowns editor keydowns were typed. Identical snapshots are parsed once;
    identity is the server's own hash of the text, never the client's sha256 field, which a forged
    log could set to skip a snapshot. Bounded: at most max_snapshots distinct snapshots and
    max_chars characters in all are parsed (a forged log cannot make the server parse without
    limit), and truncation is reported, not hidden."""
    jumps: list[AstJump] = []
    prev: AstSummary | None = None
    prev_sha: str | None = None
    keydowns = 0
    parsed = 0
    chars = 0
    truncated = False
    for e in events:
        if e.get("t_client_us") is None:
            continue
        d = e["data"]
        if e["type"] == "keydown" and d.get("target", "editor") == "editor" and not d.get("rep"):
            keydowns += 1
        elif e["type"] == "snapshot":
            text = str(d["text"])
            sha = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
            if sha == prev_sha:              # unchanged: still a snapshot boundary, nothing to parse
                keydowns = 0
                continue
            if parsed >= max_snapshots or chars + len(text) > max_chars:
                truncated = True
                break
            cur = summarize(text)
            parsed += 1
            chars += len(text)
            if prev is not None and cur.named_nodes - prev.named_nodes >= min_nodes and keydowns < max_keydowns:
                jumps.append(AstJump(e["t_client_us"] / 1e6, cur.named_nodes - prev.named_nodes, keydowns, str(d.get("reason", ""))))
            prev, prev_sha, keydowns = cur, sha, 0
    return AstTimeline(jumps, parsed, truncated, prev)
