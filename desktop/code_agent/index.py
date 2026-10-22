"""
desktop/code_agent/index.py
-------------------------------
Buscador de codigo del agente (sin LLM, sin embeddings): lo "dificil" lo hace el arnes.

Motivo (medido el 2026-10-20): los modelos pequeños (3B/8B) buscaban con `grep` frases
enteras y se fiaban del primer resultado. Un buscador de ~80 lineas puntuando FUNCIONES por
los terminos de la pregunta ya coloca la respuesta correcta entre las 3 primeras. Aqui se
hace bien: trocea el proyecto en funciones/metodos/clases (ast en Python; regex en JS; ventanas
en el resto), tokeniza partiendo identificadores (snake_case / camelCase), compara por raices
(`historial` ~ `history` ~ `histor`), expande sinonimos es->en y puntua por cobertura de TODOS
los terminos de la pregunta, con peso extra al nombre, docstring/comentarios y ruta.

Todo pasa por Workspace: ficheros protegidos y carpetas de ruido nunca entran en el indice.
"""

from __future__ import annotations

import ast
import math
import os
import re
import subprocess
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools import _scrubbed_env
from .workspace import SKIP_DIRS, Workspace, redact

MAX_FILE_BYTES = 1024 * 1024
MAX_CHUNK_CHARS = 6000
WINDOW_LINES = 50
MAX_CHUNKS = 40_000

# Carpetas que no son "el codigo del proyecto" aunque esten en el repositorio.
_INDEX_SKIP_DIRS = SKIP_DIRS | {"vendor", "third_party", "thirdparty", "exports", "node_modules"}

# Los fragmentos de texto y de modulo resumen mucho y ganarian siempre a la funcion concreta;
# los tests describen codigo ajeno: a igualdad, se prefiere la funcion del flujo real.
_KIND_WEIGHT = {"funcion": 1.0, "metodo": 1.0, "constantes": 0.9, "clase": 0.8, "modulo": 0.45, "texto": 0.45}
_TEST_WEIGHT = 0.5
_K1, _B = 1.2, 0.75

_PY = {".py"}
_JS = {".js", ".mjs", ".ts", ".tsx", ".jsx"}
_TEXT = {".md", ".txt", ".html", ".htm", ".css", ".json", ".yaml", ".yml", ".toml", ".ps1", ".sh", ".cfg", ".ini", ".sql"}

# Palabras de la pregunta que no dicen nada del codigo.
_STOP = set(
    "el la los las un una unos unas de del al y o u e a en con por para que se si no es son ser esta este esto "
    "estos estas hay como cual cuales cuando donde quien lo le les me mi tu su sus mas muy ya pero sobre entre "
    "dime dame explica explicame mira fichero ficheros archivo funcion funciones linea lineas exacta exacto codigo "
    "proyecto the of to is are how where what which does do in on and or for with this that find show tell me"
    .split()
)

# Raiz espanola (ya "stemizada") -> palabras inglesas / de codigo equivalentes.
_SYNONYMS: dict[str, list[str]] = {
    "histor": ["history", "messages", "turns"],
    "clasif": ["classify", "classifier", "intention", "router", "resolve"],
    "decid": ["decide", "choose", "select", "resolve", "if"],
    "pasa": ["pass", "send", "forward", "extend", "append"],
    "conver": ["conversation", "chat", "context", "history"],
    "mensaj": ["message", "msg"],
    "cuota": ["quota", "limit", "rate", "budget", "tokens_per_minute", "pacer", "throttle"],
    "limit": ["limit", "max", "budget", "cap"],
    "carpet": ["folder", "directory", "dir", "workspace", "path"],
    "direct": ["directory", "dir", "folder"],
    "autori": ["allow", "allowed", "authorize", "permit", "grant"],
    "permis": ["permission", "allow", "grant"],
    "permit": ["permission", "allow", "grant"],
    "compro": ["check", "validate", "verify", "ensure", "is"],
    "compru": ["check", "validate", "verify", "ensure", "is"],
    "valid": ["validate", "check", "verify"],
    "bloque": ["block", "deny", "forbid", "protect"],
    "prohib": ["deny", "forbid", "block"],
    "secret": ["secret", "redact", "password", "credential", "token", "key"],
    "contra": ["password", "secret", "credential"],
    "creden": ["credential", "secret", "password"],
    "busqu": ["search", "find", "grep", "lookup"],
    "busca": ["search", "find", "grep", "lookup"],
    "error": ["error", "exception", "fail", "raise"],
    "falla": ["fail", "error", "exception"],
    "reinic": ["restart", "reboot", "reload"],
    "config": ["config", "settings", "setting", "options"],
    "ajuste": ["settings", "setting", "config", "options"],
    "usuari": ["user", "account"],
    "ficher": ["file", "files", "path"],
    "archiv": ["file", "files", "path"],
    "lee": ["read", "load", "open", "list"],
    "leyen": ["read", "load", "open"],
    "lect": ["read", "load", "open"],
    "escrib": ["write", "save", "store", "persist"],
    "guard": ["save", "store", "persist", "write"],
    "borra": ["delete", "remove", "clear"],
    "elimin": ["delete", "remove", "drop"],
    "crea": ["create", "build", "make", "new"],
    "envi": ["send", "post", "emit", "dispatch"],
    "recib": ["receive", "get", "handle"],
    "model": ["model", "llm"],
    "agent": ["agent"],
    "herram": ["tool", "tools"],
    "tiempo": ["time", "timeout", "deadline", "seconds", "wait"],
    "esper": ["wait", "sleep", "delay", "pause"],
    "reinte": ["retry", "retries", "again"],
    "corre": ["mail", "email", "outlook", "message"],
    "notif": ["notify", "notification", "alert", "toast"],
    "avis": ["notify", "notification", "alert", "warning"],
    "cancel": ["cancel", "abort", "discard"],
    "confirm": ["confirm", "pending", "approve", "accept"],
    "pendie": ["pending", "queue", "waiting"],
    "raton": ["mouse", "pointer", "cursor"],
    "veloci": ["speed", "velocity"],
    "precio": ["price", "cost"],
    "coste": ["cost", "price", "paid"],
    "pago": ["paid", "cost", "billing"],
    "ventan": ["window", "webview", "frame"],
    "arran": ["start", "boot", "launch", "init"],
    "inici": ["start", "init", "launch", "boot"],
    "prompt": ["prompt", "system", "instruction"],
    "identi": ["identity", "name", "persona"],
    "cita": ["citation", "cite", "reference"],
    "evide": ["evidence", "proof"],
    "razon": ["think", "reasoning"],
    "contex": ["context", "window", "ctx"],
    "recort": ["truncate", "trim", "elide", "cut"],
    "puntu": ["score", "rank", "rate"],
    "prior": ["priority", "important", "importance", "score"],
    "agrup": ["group", "batch", "cluster"],
    "duplic": ["duplicate", "dedupe", "seen", "already"],
    "cache": ["cache", "cached", "memo"],
    "lista": ["list", "enumerate"],
    "devuel": ["return", "yield", "respond"],
    "respon": ["respond", "reply", "answer", "response"],
    "web": ["web", "http", "url", "internet"],
    "puent": ["bridge", "api"],
    "javasc": ["js", "javascript", "api"],
    "escrit": ["desktop"],
    "heuris": ["heuristic", "match", "rule"],
    "pantal": ["screen", "window", "ui"],
    "boton": ["button", "btn"],
    "pagina": ["page", "route", "template"],
    "base": ["base", "parent", "super"],
    "puntuac": ["score", "rank", "rating"],
    "mover": ["move", "drag"],
    "abrir": ["open", "launch", "show"],
    "cerrar": ["close", "stop", "shutdown"],
    "tabla": ["table", "schema", "db"],
    "base de": ["database", "db", "sql"],
    "intern": ["internet", "web", "http"],
}

_WORD = re.compile(r"[A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_COMMENT = re.compile(r"^\s*(?:#|//|\*|/\*|<!--)\s?(.*)$")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def stem(word: str) -> str:
    """Raiz tosca pero util entre idiomas y entre conjugaciones: quita plural, la 'n' de
    "tapan", la vocal final ("minuto"~"minute", "tapa"~"tapan") y trunca a 6 (historial~history)."""
    word = word.lower()
    if len(word) > 5 and word.endswith("es"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("s"):
        word = word[:-1]
    if len(word) >= 5 and word.endswith(("an", "en")):
        word = word[:-1]
    if len(word) >= 5 and word[-1] in "aeo":
        word = word[:-1]
    return word[:6]


def tokenize(text: str) -> list[str]:
    """Palabras ya normalizadas (sin acentos, identificadores partidos, raices)."""
    out: list[str] = []
    for token in _WORD.findall(_strip_accents(text)):
        for part in _CAMEL.sub(" ", token).replace("_", " ").split():
            part = part.lower()
            if len(part) > 1 and part not in _STOP:
                out.append(stem(part))
    return out


@dataclass(slots=True)
class Chunk:
    path: str
    start: int
    end: int
    name: str
    kind: str
    lines: list[str]
    name_tf: Counter = field(default_factory=Counter)
    doc_tf: Counter = field(default_factory=Counter)
    body_tf: Counter = field(default_factory=Counter)
    path_tf: Counter = field(default_factory=Counter)
    body_len: int = 1
    weight: float = 1.0


@dataclass(slots=True)
class Hit:
    chunk: Chunk
    score: float
    matched: list[str]

    @property
    def location(self) -> str:
        return f"{self.chunk.path}:{self.chunk.start}"


def _doc_text(lines: list[str]) -> str:
    """Comentarios de linea: donde vive el espanol y la intencion."""
    comments = []
    for line in lines:
        match = _COMMENT.match(line)
        if match and match.group(1).strip():
            comments.append(match.group(1))
    return " ".join(comments)


def _make_chunk(path: str, start: int, lines: list[str], name: str, kind: str, doc: str = "") -> Chunk:
    text = "\n".join(lines)[:MAX_CHUNK_CHARS]
    chunk = Chunk(path=path, start=start, end=start + len(lines) - 1, name=name, kind=kind, lines=lines)
    chunk.name_tf = Counter(tokenize(name))
    chunk.doc_tf = Counter(tokenize(doc + " " + _doc_text(lines)))
    chunk.body_tf = Counter(tokenize(text))
    chunk.path_tf = Counter(tokenize(path))
    chunk.body_len = max(sum(chunk.body_tf.values()), 1)
    is_test = "/tests/" in f"/{path}" or Path(path).name.startswith("test_")
    chunk.weight = _KIND_WEIGHT.get(kind, 1.0) * (_TEST_WEIGHT if is_test else 1.0)
    return chunk


def _python_chunks(rel: str, source: str) -> list[Chunk]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return _window_chunks(rel, source.splitlines())
    lines = source.splitlines()
    chunks: list[Chunk] = []

    def add(node: ast.AST, name: str, kind: str, end: int | None = None) -> None:
        first = (min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno]))
        last = end or getattr(node, "end_lineno", None) or node.lineno
        doc = ast.get_docstring(node) or ""
        chunks.append(_make_chunk(rel, first, lines[first - 1: last], name, kind, doc))

    def add_constants(group: list[ast.stmt]) -> None:
        """Asignaciones de modulo contiguas (+ los comentarios que las explican): listas de
        patrones, tablas, configuracion — donde suele vivir una regla (p. ej. ficheros prohibidos)."""
        first = group[0].lineno
        while first - 2 >= 0 and lines[first - 2].strip().startswith("#"):
            first -= 1
        # Trozos de <= 25 lineas cortando entre sentencias, cada uno con TODOS sus nombres
        # (el nombre de un trozo largo se truncaba y el simbolo no se podia localizar).
        piece: list[ast.stmt] = []
        piece_first = first
        def flush() -> None:
            names = []
            for stmt in piece:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                names += [t.id for t in targets if isinstance(t, ast.Name)]
            last_line = piece[-1].end_lineno or piece[-1].lineno
            if names:
                chunks.append(_make_chunk(rel, piece_first, lines[piece_first - 1: last_line], ", ".join(names), "constantes"))
        for stmt in group:
            stmt_end = stmt.end_lineno or stmt.lineno
            if piece and stmt_end - piece_first + 1 > 25:
                flush()
                piece, piece_first = [], stmt.lineno
            piece.append(stmt)
        if piece:
            flush()

    module_doc = ast.get_docstring(tree)
    if module_doc:
        chunks.append(_make_chunk(rel, 1, lines[: min(len(lines), 30)], Path(rel).stem, "modulo", module_doc))
    pending: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            pending.append(node)
            continue
        if pending:
            add_constants(pending)
            pending = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node, node.name, "funcion")
        elif isinstance(node, ast.ClassDef):
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            header_end = (methods[0].lineno - 1) if methods else node.end_lineno
            add(node, node.name, "clase", end=min(header_end, node.lineno + 40))
            for method in methods:
                add(method, f"{node.name}.{method.name}", "metodo")
    if pending:
        add_constants(pending)
    return chunks


_JS_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s*\*?\s+(\w+)|class\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|function|\w+\s*=>))"
)


def _js_chunks(rel: str, source: str) -> list[Chunk]:
    lines = source.splitlines()
    starts = [(i, m) for i, line in enumerate(lines) if (m := _JS_DEF.match(line))]
    if not starts:
        return _window_chunks(rel, lines)
    chunks = []
    for index, (i, match) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        end = min(end, i + 80)
        name = match.group(1) or match.group(2) or match.group(3) or "bloque"
        chunks.append(_make_chunk(rel, i + 1, lines[i:end], name, "funcion"))
    return chunks


def _window_chunks(rel: str, lines: list[str]) -> list[Chunk]:
    chunks = []
    heading = Path(rel).name
    for start in range(0, len(lines), WINDOW_LINES):
        window = lines[start: start + WINDOW_LINES]
        for line in window:
            if line.startswith("#"):
                heading = line.lstrip("# ").strip() or heading
                break
        chunks.append(_make_chunk(rel, start + 1, window, heading, "texto"))
    return chunks


def chunk_file(rel: str, source: str) -> list[Chunk]:
    suffix = Path(rel).suffix.lower()
    if suffix in _PY:
        return _python_chunks(rel, source)
    if suffix in _JS:
        return _js_chunks(rel, source)
    return _window_chunks(rel, source.splitlines())


_VERB_ENDINGS = ("a", "an", "e", "en", "o", "ido", "ado", "ando", "iendo", "yen", "yendo")


def _verb_forms(word: str) -> list[str]:
    """Formas conjugadas de un infinitivo espanol (leer -> lee, leen, leido...): en los comentarios
    del codigo casi nunca aparece el infinitivo que usa la pregunta."""
    if len(word) >= 4 and word.endswith(("ar", "er", "ir")):
        root = word[:-2]
        return [stem(root + ending) for ending in _VERB_ENDINGS]
    return []


def expand_query(question: str) -> list[list[str]]:
    """Grupos de raices: cada termino de la pregunta + sus sinonimos. Un grupo cuenta como
    cubierto si CUALQUIERA de sus raices aparece."""
    groups: list[list[str]] = []
    seen: set[str] = set()
    for token in _WORD.findall(_strip_accents(question)):
        for part in _CAMEL.sub(" ", token).replace("_", " ").split():
            word = part.lower()
            if len(word) < 2 or word in _STOP:
                continue
            base = stem(word)
            if base in seen:
                continue
            seen.add(base)
            alts = [base] + _verb_forms(word)
            for key, synonyms in _SYNONYMS.items():
                # clave[:5]: las claves son raices escritas a mano y stem() quita la vocal final
                if len(base) >= 3 and base.startswith(key[:5]):
                    alts += [stem(s) for s in synonyms]
            groups.append(list(dict.fromkeys(alts)))
    return groups


def _tracked_files(ws: Workspace) -> list[Path] | None:
    """Ficheros del repositorio respetando .gitignore (trackeados + nuevos no ignorados);
    None si la carpeta no es un repositorio git."""
    if not (ws.root / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ws.root, capture_output=True,
            timeout=30, env=_scrubbed_env(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    paths = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        candidate = ws.root / raw.decode("utf-8", errors="replace")
        parts = {p.lower() for p in candidate.relative_to(ws.root).parts[:-1]}
        if parts & _INDEX_SKIP_DIRS or ws.is_denied(candidate) or candidate.is_symlink():
            continue
        paths.append(candidate)
    return paths


class CodeIndex:
    """Indice incremental de un Workspace: solo se vuelven a trocear los ficheros que cambian."""

    def __init__(self, workspace: Workspace, exclude_prefixes: tuple[str, ...] = ()) -> None:
        self.ws = workspace
        # Rutas (prefijos relativos) que no se indexan: p. ej. las preguntas de evaluacion, que
        # contienen su propio texto y "se contestarian a si mismas".
        self._exclude = tuple(p.replace("\\", "/") for p in exclude_prefixes)
        self._files: dict[str, tuple[float, int, list[Chunk]]] = {}
        self._chunks: list[Chunk] = []
        self._df: Counter = Counter()
        self._postings: dict[str, list[int]] = {}
        self._avg_len = 1.0

    # ── Construccion ─────────────────────────────────────────────────────────

    def refresh(self) -> int:
        """Reindexa lo que cambio. Devuelve el numero de ficheros (re)procesados."""
        seen: set[str] = set()
        changed = 0
        listed = _tracked_files(self.ws)
        if listed is None:
            listed = [
                p for p in self.ws.iter_files()
                if not ({part.lower() for part in p.relative_to(self.ws.root).parts[:-1]} & _INDEX_SKIP_DIRS)
            ]
        for path in listed:
            suffix = path.suffix.lower()
            if suffix not in _PY | _JS | _TEXT:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_BYTES or stat.st_size == 0:
                continue
            rel = self.ws.rel(path)
            if self._exclude and rel.startswith(self._exclude):
                continue
            seen.add(rel)
            cached = self._files.get(rel)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                continue
            try:
                source = path.read_text(encoding="utf-8-sig", errors="replace")   # -sig: algunos ficheros llevan BOM y ast.parse falla
            except OSError:
                continue
            if "\x00" in source[:4096]:
                continue
            self._files[rel] = (stat.st_mtime, stat.st_size, chunk_file(rel, source))
            changed += 1
        for gone in set(self._files) - seen:
            del self._files[gone]
            changed += 1
        if changed or not self._chunks:
            self._chunks = [c for _, _, chunks in self._files.values() for c in chunks][:MAX_CHUNKS]
            self._df = Counter()
            self._postings = {}
            for position, chunk in enumerate(self._chunks):
                for stem_ in set(chunk.name_tf) | set(chunk.doc_tf) | set(chunk.body_tf) | set(chunk.path_tf):
                    self._df[stem_] += 1
                    self._postings.setdefault(stem_, []).append(position)
            self._avg_len = sum(c.body_len for c in self._chunks) / max(len(self._chunks), 1)
        return changed

    @property
    def size(self) -> int:
        return len(self._chunks)

    # ── Consulta estructural (mapa del proyecto, verificacion de citas) ──────

    def file_paths(self) -> list[str]:
        return sorted(self._files)

    def file_chunks(self, path: str) -> list[Chunk]:
        entry = self._files.get(path)
        return list(entry[2]) if entry else []

    def line_count(self, path: str) -> int:
        return max((c.end for c in self.file_chunks(path)), default=0)

    def symbols(self, path: str) -> list[tuple[str, int, int]]:
        """(nombre, primera_linea, ultima_linea) de las funciones, clases y metodos de un fichero.
        El trozo de una clase solo cubre su cabecera: aqui se amplia hasta su ultimo metodo."""
        chunks = self.file_chunks(path)
        result: list[tuple[str, int, int]] = []
        for chunk in chunks:
            if chunk.kind not in ("funcion", "clase", "metodo"):
                continue
            end = chunk.end
            if chunk.kind == "clase":
                end = max([end] + [c.end for c in chunks if c.kind == "metodo" and c.name.startswith(chunk.name + ".")])
            result.append((chunk.name, chunk.start, end))
        return sorted(result, key=lambda s: s[1])

    # ── Busqueda ─────────────────────────────────────────────────────────────

    def search(self, question: str, k: int = 5, per_file: int = 2, extra_terms: list[str] | None = None) -> list[Hit]:
        """`extra_terms`: palabras clave aportadas por el LLM (vocabulario del codigo). Suman puntuacion
        pero NO cuentan para la cobertura: son opcionales, la pregunta original manda."""
        groups = expand_query(question)
        extra_groups = [[stem(w)] for w in dict.fromkeys(tokenize(" ".join(extra_terms or [])))] if extra_terms else []
        extra_groups = [g for g in extra_groups if g not in groups]
        if (not groups and not extra_groups) or not self._chunks:
            return []
        total = len(self._chunks)

        def idf(stem_: str) -> float:
            return math.log(1 + total / (1 + self._df.get(stem_, 0)))

        # Un termino que no aparece en NINGUN fragmento (relleno: "evita", "pepo"...) no puede
        # contar para la cobertura; y los comunes pesan poco: la cobertura se mide por rareza.
        groups = [g for g in groups if any(self._df.get(alt) for alt in g)]
        extra_groups = [g for g in extra_groups if any(self._df.get(alt) for alt in g)]
        if not groups and not extra_groups:
            return []
        group_weight = {id(g): max(idf(alt) for alt in g if self._df.get(alt)) for g in groups}
        total_weight = sum(group_weight.values()) or 1.0

        # Solo se puntuan los fragmentos que contienen alguna raiz de la pregunta (indice invertido).
        candidates: set[int] = set()
        for group in [*groups, *extra_groups]:
            for alt in group:
                candidates.update(self._postings.get(alt, ()))

        def saturate(tf: int, length: int) -> float:
            """BM25: la frecuencia satura y los fragmentos largos no ganan solo por ser largos."""
            return tf * (_K1 + 1) / (tf + _K1 * (1 - _B + _B * length / self._avg_len))

        scored: list[Hit] = []
        for position in candidates:
            chunk = self._chunks[position]
            score = 0.0
            matched: list[str] = []
            covered = 0.0
            for group in groups:
                best = 0.0
                for alt in group:
                    value = 0.0
                    if chunk.name_tf.get(alt):
                        value += 3.0
                    if chunk.path_tf.get(alt):
                        value += 1.5
                    if chunk.doc_tf.get(alt):
                        value += 1.5 * saturate(chunk.doc_tf[alt], chunk.body_len)
                    if chunk.body_tf.get(alt):
                        value += saturate(chunk.body_tf[alt], chunk.body_len)
                    best = max(best, value * idf(alt))
                if best > 0:
                    score += best
                    matched.append(group[0])
                    covered += group_weight[id(group)]
            extra_score = 0.0
            for group in extra_groups:
                alt = group[0]
                value = 0.0
                if chunk.name_tf.get(alt):
                    value += 3.0
                if chunk.path_tf.get(alt):
                    value += 1.5
                if chunk.doc_tf.get(alt):
                    value += 1.5 * saturate(chunk.doc_tf[alt], chunk.body_len)
                if chunk.body_tf.get(alt):
                    value += saturate(chunk.body_tf[alt], chunk.body_len)
                if value:
                    extra_score += value * idf(alt)
                    matched.append(alt)
            if not matched:
                continue
            coverage = covered / total_weight
            scored.append(Hit(chunk, (score * coverage * coverage + 0.5 * extra_score) * chunk.weight, matched))
        scored.sort(key=lambda h: h.score, reverse=True)

        hits: list[Hit] = []
        taken: Counter = Counter()
        for hit in scored:
            if taken[hit.chunk.path] >= per_file:
                continue
            taken[hit.chunk.path] += 1
            hits.append(hit)
            if len(hits) >= k:
                break
        return hits


# ── Presentacion ─────────────────────────────────────────────────────────────

def _snippet(hit: Hit, matched_stems: set[str], max_lines: int = 14) -> list[str]:
    """Primera linea + ventanas alrededor de las lineas que coinciden; con numeros de linea reales."""
    chunk = hit.chunk
    keep: set[int] = {0}
    hit_lines = [
        i for i, line in enumerate(chunk.lines)
        if matched_stems & set(tokenize(line))
    ]
    for i in hit_lines[:4]:
        keep.update(range(max(i - 1, 0), min(i + 2, len(chunk.lines))))
    chosen = sorted(keep)[:max_lines]
    out, previous = [], None
    for i in chosen:
        if previous is not None and i != previous + 1:
            out.append("      ...")
        out.append(f"{chunk.start + i:>6}  {chunk.lines[i][:150]}")
        previous = i
    return out


def format_hits(hits: list[Hit], question: str, detail: int = 3) -> str:
    """Los `detail` primeros con sus lineas clave; el resto, una linea cada uno. Una lista ancha y
    barata sube el recall (medido: recall@8 > recall@5) sin gastar el contexto de un modelo pequeño."""
    if not hits:
        return "Sin resultados para esa pregunta. Prueba con otras palabras (nombres de funciones o terminos en ingles)."
    groups = expand_query(question)
    stem_sets = {g[0]: set(g) for g in groups}
    blocks = []
    compact = []
    for number, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        header = f"{number}. {chunk.path}:{chunk.start}-{chunk.end}  {chunk.name} ({chunk.kind})"
        if number > detail:
            compact.append(header)
            continue
        wanted: set[str] = set()
        for term in hit.matched:
            wanted |= stem_sets.get(term, {term})
        blocks.append(f"{header}  [coincide: {', '.join(hit.matched)}]\n" + "\n".join(_snippet(hit, wanted)))
    text = "\n\n".join(blocks)
    if compact:
        text += "\n\nOtros candidatos (sin detalle; leelos con read_file si hacen falta):\n" + "\n".join(compact)
    return redact(text)


FIND_CODE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "find_code",
        "description": (
            "Busca en el codigo del proyecto los fragmentos (funciones, metodos, clases) mas relevantes para una "
            "pregunta o idea, en español o en ingles. Devuelve ruta:linea y las lineas clave. USALA PRIMERO, antes de "
            "grep. Los resultados pueden no ser los correctos: leelos con read_file y verifica."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "La pregunta o la idea, en pocas palabras."},
                "keywords": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Opcional: palabras clave EN INGLES como aparecerian en el codigo (nombres de funciones, variables). Util si la primera busqueda no encuentra nada.",
                },
            },
            "required": ["question"],
        },
    },
}
