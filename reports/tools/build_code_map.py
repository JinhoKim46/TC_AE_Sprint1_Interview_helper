"""Build `reports/code_map.json`: a static map of what every script does and how the parts connect.

Run it from the project root:

    uv run python reports/tools/build_code_map.py              # code_map.json + code-flow-report.html
    uv run python reports/tools/build_code_map.py --json-only  # only the JSON

Why static analysis (Python's `ast`) instead of importing the code: it is fast, needs no API keys or
database, cannot trigger side effects (the Streamlit pages run UI code at import time), and gives exact
line numbers. The price is that some calls can't be resolved without running the code, e.g. a method
called on an object whose type is unknown. Those are listed under `unresolved` instead of guessed.

What it extracts, per module under `src/interview_app/`, `app/` and `lab/`:
- the docstring, the imports (internal ones resolved to module ids) and every function, class and method
  with its signature, first docstring paragraph and line numbers;
- call edges between functions, resolved through imports, module aliases (`eng.answer`), `self.method`,
  typed parameters (`llm: LLMClient` -> `llm.chat_json`), dataclass fields (`deps.make_llm(...)`),
  attribute chains (`deps.guard.check_answer`) and return annotations;
- which functions render which prompt templates, and the `{% include %}` tree between templates;
- every model call ("agent"): its call-log role, the `Settings.models.<x>` it uses, the pydantic schema
  it validates against, its settings and the message roles and templates that build its input;
- which SQLModel tables each function reads, writes or deletes.

The output is deterministic (sorted, no timestamps), so a diff of code_map.json shows what changed.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "reports" / "code_map.json"
PROMPTS_DIR = ROOT / "src" / "interview_app" / "prompts"

# Layers, in the left-to-right order the report draws them.
LAYERS = [
    ("ui", "UI (Streamlit)"),
    ("lab", "Lab"),
    ("core", "Core"),
    ("evaluation", "Evaluation"),
    ("security", "Security"),
    ("llm", "LLM gateway"),
    ("foundation", "Config + DB"),
]

# The two model gateways (CLAUDE.md: all model calls go through these). A call that resolves to one of
# them is a model call site; the argument positions say where role, messages and schema are.
GATEWAYS = {
    "interview_app.llm.client:LLMClient.chat_json": "chat_json",
    "interview_app.llm.client:LLMClient.chat": "chat",
    "interview_app.llm.client:LLMClient.speech": "speech",
    "interview_app.llm.decide:DecisionClient.decide": "decide",
}
MODEL_SETTING_KWARGS = ("temperature", "max_tokens", "reasoning_effort")

BUILTIN_NAMES = set(dir(builtins))
# Methods of builtin types (str, list, dict...). A call like `text.strip()` on an untyped name is not an
# interesting "unresolved" call, so these are counted separately.
BUILTIN_METHODS = {
    name
    for t in (str, list, dict, set, tuple, int, float, bytes)
    for name in dir(t)
    if not name.startswith("_")
}
JINJA_WORDS = {
    "for", "in", "if", "else", "elif", "endif", "endfor", "include", "not", "and", "or", "is", "loop",
    "true", "false", "none", "True", "False", "None", "set", "endset", "macro", "endmacro", "block",
    "endblock", "with", "endwith", "recursive",
}  # fmt: skip


# --------------------------------------------------------------------------- small helpers


def unwrap(text: str) -> str:
    """Join hard-wrapped docstring lines into paragraphs; keep list items and code lines separate."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines: list[str] = []
        for raw in block.split("\n"):
            line = raw.rstrip()
            starts_item = re.match(r"\s*(?:[-*]\s|\d+\.\s|\w[\w./]*\s{2,}\S)", line)
            is_code = raw.startswith("    ")
            if lines and not starts_item and not is_code and not lines[-1].startswith("    "):
                lines[-1] = f"{lines[-1]} {line.strip()}"
            else:
                lines.append(line if is_code else line.strip())
        paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def first_paragraph(doc: str | None) -> str:
    if not doc:
        return ""
    return unwrap(re.split(r"\n\s*\n", doc.strip())[0])


def src(node: ast.AST | None, limit: int = 160) -> str:
    if node is None:
        return ""
    text = ast.unparse(node)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def const_str(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def iter_scope(nodes: list[ast.stmt]):
    """Walk statements without entering nested functions or classes (those are their own scopes)."""
    nested = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    stack: list[ast.AST] = [n for n in reversed(nodes) if not isinstance(n, nested)]
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(list(ast.iter_child_nodes(node))):
            if not isinstance(child, nested):
                stack.append(child)


def scope_defs(nodes: list[ast.stmt]):
    """The functions defined directly in a scope (also inside its if / with / for blocks)."""
    stack: list[ast.AST] = list(reversed(nodes))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node
            continue
        if isinstance(node, ast.ClassDef):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def attr_chain(node: ast.AST) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; None if the chain doesn't start at a plain name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return list(reversed(parts))
    return None


# --------------------------------------------------------------------------- data model


@dataclass
class Module:
    id: str
    path: str
    layer: str
    tree: ast.Module
    source: str
    is_test: bool = False
    names: dict[str, tuple] = field(default_factory=dict)  # name -> binding (see bind_names)
    consts: dict[str, ast.AST] = field(default_factory=dict)  # module-level NAME = value
    imports: set[str] = field(default_factory=set)
    external_imports: set[str] = field(default_factory=set)


@dataclass
class Symbol:
    id: str
    module: str
    qualname: str
    kind: str  # function | method | nested | class | field | property | module
    node: ast.AST | None
    cls: str | None = None  # owning class symbol id, for methods / fields / properties
    parent: str | None = None  # enclosing function symbol id, for nested functions
    data: dict[str, Any] = field(default_factory=dict)


class CodeMap:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.modules: dict[str, Module] = {}
        self.symbols: dict[str, Symbol] = {}
        self.class_attrs: dict[str, dict[str, Any]] = {}  # class id -> attribute name -> type
        self.class_bases: dict[str, list[str]] = {}
        self.tables: set[str] = set()  # class ids of SQLModel tables
        self.edges: dict[tuple[str, str, str], set[int]] = {}
        self.call_sites: list[dict] = []  # every resolved call, for one-hop argument tracing
        self.model_calls: list[dict] = []
        self.render_sites: list[dict] = []
        self.stats = {"resolved": 0, "external": 0, "builtin": 0, "unresolved": 0}
        self._return_cache: dict[str, Any] = {}
        self._in_progress: set[str] = set()
        self._scopes: dict[str, Scope] = {}

    # ----------------------------------------------------------------------- discovery

    def discover(self) -> None:
        roots = [
            ("src/interview_app", "interview_app", False),
            ("app", "app", False),
            ("lab", "lab", False),
            ("tests", "tests", True),
        ]
        for rel, prefix, is_test in roots:
            base = self.root / rel
            pattern = "*.py" if rel in ("lab", "tests") else "**/*.py"
            for path in sorted(base.glob(pattern)):
                parts = list(path.relative_to(base).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                mod_id = ".".join([prefix, *parts])
                text = path.read_text()
                self.modules[mod_id] = Module(
                    id=mod_id,
                    path=str(path.relative_to(self.root)),
                    layer="test" if is_test else layer_of(mod_id),
                    tree=ast.parse(text, filename=str(path)),
                    source=text,
                    is_test=is_test,
                )
        # Streamlit puts app/ on sys.path and lab scripts import their siblings, so `from ui_common
        # import x` means app/ui_common.py. Bare names map to these modules.
        self.short_names = {}
        for mod_id in self.modules:
            head, _, last = mod_id.rpartition(".")
            if head in ("app", "lab"):
                self.short_names[last] = mod_id

    # ----------------------------------------------------------------------- pass 1: symbols

    def collect_symbols(self) -> None:
        for mod in self.modules.values():
            self.symbols[f"{mod.id}:<module>"] = Symbol(
                f"{mod.id}:<module>", mod.id, "<module>", "module", None
            )
            for node in mod.tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    self._add_function(mod, node, node.name, "function")
                elif isinstance(node, ast.ClassDef):
                    self._add_class(mod, node)
                elif isinstance(node, ast.Assign | ast.AnnAssign):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        if isinstance(t, ast.Name) and node.value is not None:
                            mod.consts[t.id] = node.value

    def _add_function(self, mod: Module, node, qualname: str, kind: str, cls: str | None = None, parent=None):
        sid = f"{mod.id}:{qualname}"
        decorators = [src(d, 60) for d in node.decorator_list]
        if cls and "property" in decorators:
            kind = "property"
        self.symbols[sid] = Symbol(sid, mod.id, qualname, kind, node, cls=cls, parent=parent)
        for child in ast.walk(node):
            if child is node:
                continue
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and self._direct_parent(node, child):
                self._add_function(mod, child, f"{qualname}.{child.name}", "nested", parent=sid)

    @staticmethod
    def _direct_parent(outer, inner) -> bool:
        """Is `inner` defined directly in `outer`'s body (not inside a deeper def or class)?"""
        return any(n is inner for n in scope_defs(outer.body))

    def _add_class(self, mod: Module, node: ast.ClassDef) -> None:
        cid = f"{mod.id}:{node.name}"
        self.symbols[cid] = Symbol(cid, mod.id, node.name, "class", node)
        if any(k.arg == "table" and getattr(k.value, "value", None) is True for k in node.keywords):
            self.tables.add(cid)
        for item in node.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                self._add_function(mod, item, f"{node.name}.{item.name}", "method", cls=cid)

    # ----------------------------------------------------------------------- pass 2: names

    def bind_names(self) -> None:
        """Per module: which name means which symbol, module, constant or external object."""
        for mod in self.modules.values():
            for node in mod.tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                    mod.names[node.name] = ("sym", f"{mod.id}:{node.name}")
            for node in iter_scope(mod.tree.body):
                for local, binding in self.import_bindings(node, mod):
                    mod.names[local] = binding
            for name, value in mod.consts.items():
                if name in mod.names:
                    continue
                # `continue_interview = respond`: an alias of a function is the function itself.
                if isinstance(value, ast.Name) and mod.names.get(value.id, ("",))[0] == "sym":
                    mod.names[name] = mod.names[value.id]
                    self.symbols[mod.names[value.id][1]].data.setdefault("aliases", []).append(name)
                else:
                    mod.names[name] = ("const", mod.id, name)

    def import_bindings(self, node: ast.AST, mod: Module) -> list[tuple[str, tuple]]:
        """The names an import statement binds, and what each one means. Also records the dependency."""
        out: list[tuple[str, tuple]] = []
        if isinstance(node, ast.Import):
            for a in node.names:
                target = self._module_for(a.name)
                local = a.asname or a.name.split(".")[0]
                if target:
                    out.append((local, ("mod", target)))
                    mod.imports.add(target)
                else:
                    out.append((local, ("extmod", a.name if a.asname else local)))
                    mod.external_imports.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            base = self._module_for(node.module)
            for a in node.names:
                local = a.asname or a.name
                if base and f"{base}.{a.name}" in self.modules:
                    out.append((local, ("mod", f"{base}.{a.name}")))
                    mod.imports.add(f"{base}.{a.name}")
                elif base:
                    out.append((local, ("from", base, a.name)))
                    mod.imports.add(base)
                else:
                    out.append((local, ("ext", f"{node.module}.{a.name}")))
                    mod.external_imports.add(node.module.split(".")[0])
        return out

    def _module_for(self, dotted: str) -> str | None:
        if dotted in self.modules:
            return dotted
        if dotted in self.short_names:
            return self.short_names[dotted]
        return None

    def lookup(self, mod_id: str, name: str, depth: int = 0) -> tuple | None:
        """Resolve `name` in a module, following re-exports (`from x import y` in a package __init__)."""
        mod = self.modules.get(mod_id)
        if mod is None or depth > 6:
            return None
        binding = mod.names.get(name)
        if binding is None:
            sub = f"{mod_id}.{name}"
            return ("mod", sub) if sub in self.modules else None
        if binding[0] == "from":
            return self.lookup(binding[1], binding[2], depth + 1) or ("ext", f"{binding[1]}.{binding[2]}")
        return binding

    # ----------------------------------------------------------------------- types

    def ann_type(self, node: ast.AST | None, mod_id: str) -> Any:
        """A type annotation -> an internal class id, ("list", t), ("tuple", [..]), ("callable", t), "@db"."""
        if node is None:
            return None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                return self.ann_type(ast.parse(node.value, mode="eval").body, mod_id)
            except SyntaxError:
                return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self.ann_type(node.left, mod_id) or self.ann_type(node.right, mod_id)
        if isinstance(node, ast.Subscript):
            base = src(node.value).split(".")[-1]
            inner = node.slice
            elts = inner.elts if isinstance(inner, ast.Tuple) else [inner]
            if base in ("list", "Sequence", "Iterator", "Iterable", "Generator", "set", "frozenset"):
                t = self.ann_type(elts[0], mod_id)
                return ("list", t) if t else None
            if base == "tuple":
                return ("tuple", [self.ann_type(e, mod_id) for e in elts])
            if base == "Optional":
                return self.ann_type(elts[0], mod_id)
            if base == "Callable" and len(elts) == 2:
                return ("callable", self.ann_type(elts[1], mod_id))
            return None
        chain = attr_chain(node)
        if not chain:
            return None
        binding = self.lookup(mod_id, chain[0])
        for part in chain[1:]:
            if binding and binding[0] == "mod":
                binding = self.lookup(binding[1], part)
            else:
                return None
        if binding and binding[0] == "sym" and self.symbols[binding[1]].kind == "class":
            return binding[1]
        if binding and binding[0] == "const":
            # A type alias such as `Recorder = Callable[[CallRecord], None]`.
            value = self.modules[binding[1]].consts.get(binding[2])
            if isinstance(value, ast.Subscript | ast.BinOp):
                return self.ann_type(value, binding[1])
        if binding and binding[0] == "ext" and binding[1] in ("sqlmodel.Session", "sqlalchemy.orm.Session"):
            return "@db"
        if binding and binding[0] in ("ext", "extmod") and binding[1] != "typing.Any":
            return ("ext", binding[1])  # a third-party or stdlib type (Engine, Path, httpx.Client...)
        return None

    def collect_class_attrs(self) -> None:
        """Attribute types per class: annotated fields, plus `self.x = <typed param>` in methods."""
        for sym in list(self.symbols.values()):
            if sym.kind != "class":
                continue
            attrs: dict[str, Any] = {}
            mod_id = sym.module
            node = sym.node
            self.class_bases[sym.id] = [
                b[1]
                for b in (self._resolve_expr_binding(base, mod_id) for base in node.bases)
                if b and b[0] == "sym"
            ]
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    t = self.ann_type(item.annotation, mod_id)
                    attrs[item.target.id] = t
                    if isinstance(t, tuple) and t[0] == "callable":
                        # An injected callable (e.g. EngineDeps.make_llm): a symbol of its own, so calls
                        # through it and the functions bound to it can be drawn.
                        fid = f"{sym.id}.{item.target.id}"
                        self.symbols[fid] = Symbol(
                            fid, mod_id, f"{sym.qualname}.{item.target.id}", "field", item, cls=sym.id
                        )
                elif isinstance(item, ast.FunctionDef):
                    params = {
                        a.arg: self.ann_type(a.annotation, mod_id)
                        for a in item.args.args + item.args.kwonlyargs
                    }
                    if "property" in [src(d) for d in item.decorator_list]:
                        attrs.setdefault(item.name, self.ann_type(item.returns, mod_id))
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                            t = stmt.targets[0]
                            if (
                                isinstance(t, ast.Attribute)
                                and isinstance(t.value, ast.Name)
                                and t.value.id == "self"
                            ):
                                attrs.setdefault(t.attr, self._simple_type(stmt.value, params, mod_id))
            self.class_attrs[sym.id] = attrs

    def _simple_type(self, node: ast.AST, params: dict, mod_id: str) -> Any:
        if isinstance(node, ast.Name):
            return params.get(node.id)
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                if t := self._simple_type(v, params, mod_id):
                    return t
        if isinstance(node, ast.Call):
            b = self._resolve_expr_binding(node.func, mod_id)
            if b and b[0] == "sym" and self.symbols[b[1]].kind == "class":
                return b[1]
            if b and b[0] in ("ext", "extmod"):
                return ("ext", f"{b[1]}()")  # e.g. self.sdk = sdk or OpenAI(...)
        return None

    def _resolve_expr_binding(self, node: ast.AST, mod_id: str, local: dict | None = None) -> tuple | None:
        chain = attr_chain(node)
        if not chain:
            return None
        binding = (local or {}).get(chain[0]) or self.lookup(mod_id, chain[0])
        if binding and binding[0] == "from":
            binding = self.lookup(binding[1], binding[2]) or ("ext", f"{binding[1]}.{binding[2]}")
        for part in chain[1:]:
            if binding and binding[0] == "mod":
                binding = self.lookup(binding[1], part)
            elif binding and binding[0] == "extmod" or binding and binding[0] == "ext":
                binding = ("ext", f"{binding[1]}.{part}")
            else:
                return None
        return binding

    def find_member(self, cls_id: str, name: str) -> str | None:
        """A method, property or field symbol on a class or its internal bases."""
        seen = [cls_id]
        while seen:
            c = seen.pop(0)
            cand = f"{c}.{name}"
            if cand in self.symbols:
                return cand
            seen.extend(self.class_bases.get(c, []))
        return None

    def attr_type(self, cls_id: str, name: str) -> Any:
        stack = [cls_id]
        while stack:
            c = stack.pop(0)
            if name in self.class_attrs.get(c, {}):
                return self.class_attrs[c][name]
            stack.extend(self.class_bases.get(c, []))
        return None

    def return_type(self, sid: str) -> Any:
        """A function's return annotation, or the class it visibly returns (`return Cls(...)`)."""
        if sid in self._return_cache:
            return self._return_cache[sid]
        sym = self.symbols.get(sid)
        if sym is None or sym.node is None or sym.kind == "class":
            return sid if sym and sym.kind == "class" else None
        if sym.kind == "field":
            return None
        result = self.ann_type(sym.node.returns, sym.module)
        if result is None and sid not in self._in_progress:
            self._in_progress.add(sid)
            scope = self.scope_for(sym)
            for node in iter_scope(sym.node.body):
                if isinstance(node, ast.Return) and node.value is not None:
                    result = scope.type_of(node.value)
                    if result:
                        break
            self._in_progress.discard(sid)
        self._return_cache[sid] = result
        return result

    # ----------------------------------------------------------------------- pass 3: analysis

    def scope_for(self, sym: Symbol) -> Scope:
        """One cached, inferred Scope per symbol (return-type lookups ask for the same scopes often)."""
        scope = self._scopes.get(sym.id)
        if scope is None:
            scope = self._scopes[sym.id] = Scope(self, sym)
            scope.infer()
        return scope

    def analyse(self) -> None:
        for sym in list(self.symbols.values()):
            if sym.kind in ("class", "field"):
                continue
            self.scope_for(sym).resolve()
        self._trace_messages()

    def add_edge(self, src_id: str, dst_id: str, kind: str, line: int) -> None:
        if src_id == dst_id and kind != "call":
            return
        self.edges.setdefault((src_id, dst_id, kind), set()).add(line)

    def _trace_messages(self) -> None:
        """Fill in each model call's message builder, roles and templates (one hop through parameters)."""
        for mc in self.model_calls:
            builders = mc.pop("_builders")
            param = mc.pop("_messages_param")
            if param is not None:
                # `messages` is a parameter: look at what the callers passed for it.
                fn_sym = self.symbols[mc["site"]]
                pos = [a.arg for a in fn_sym.node.args.args].index(param) if fn_sym.node else -1
                for cs in self.call_sites:
                    if mc["site"] not in cs["targets"]:
                        continue
                    call: ast.Call = cs["node"]
                    arg = next((k.value for k in call.keywords if k.arg == param), None)
                    if arg is None and 0 <= pos < len(call.args):
                        arg = call.args[pos]
                    if arg is not None:
                        builders |= cs["scope"].builders_of(arg)
            mc["messages_builders"] = sorted(builders)
            roles: set[str] = set()
            templates: set[str] = set()
            for b in builders:
                for sid in self._reachable(b, depth=3):
                    roles |= self.symbols[sid].data.get("message_roles", set())
                    templates |= set(self.symbols[sid].data.get("templates", []))
            mc["message_roles"] = sorted(roles)
            mc["templates"] = sorted(templates)

    def _reachable(self, start: str, depth: int) -> list[str]:
        out, frontier = [start], [start]
        for _ in range(depth):
            nxt = []
            for s in frontier:
                for (a, b, kind), _lines in self.edges.items():
                    if a == s and kind in ("call", "binds") and b not in out and b in self.symbols:
                        out.append(b)
                        nxt.append(b)
            frontier = nxt
        return out


class Scope:
    """One function body (or a module's top-level code): local types, then call resolution."""

    def __init__(self, cm: CodeMap, sym: Symbol):
        self.cm = cm
        self.sym = sym
        self.mod = cm.modules[sym.module]
        node = sym.node
        self.body = (
            node.body
            if node is not None
            else [
                n
                for n in self.mod.tree.body
                if not isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            ]
        )
        self.types: dict[str, Any] = {}
        self.values: dict[str, ast.AST] = {}  # last value assigned to a local name
        self.params: list[str] = []
        self.locals_fns: dict[str, str] = {}  # nested function name -> symbol id
        # Imports inside a function body (used to avoid import cycles or slow imports at start-up).
        self.local_names: dict[str, tuple] = {}
        # Enclosing functions' nested defs and typed names are visible too (closures).
        chain = []
        cur: Symbol | None = sym
        while cur is not None:
            chain.append(cur)
            cur = cm.symbols.get(cur.parent) if cur.parent else None
        for s in reversed(chain):
            if s.node is None:
                continue
            for n in iter_scope(s.node.body):
                for local, binding in cm.import_bindings(n, self.mod):
                    self.local_names[local] = binding
            for n in scope_defs(s.node.body):
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
                    nid = f"{s.id}.{n.name}" if s.kind != "module" else None
                    if nid and nid in cm.symbols:
                        self.locals_fns[n.name] = nid
            if s is not sym:
                outer = cm.scope_for(s)
                self.types.update(outer.types)
                self.values.update(outer.values)
        if node is not None:
            self._bind_params()

    def lookup(self, name: str) -> tuple | None:
        binding = self.local_names.get(name)
        if binding and binding[0] == "from":
            return self.cm.lookup(binding[1], binding[2]) or ("ext", f"{binding[1]}.{binding[2]}")
        return binding or self.cm.lookup(self.sym.module, name)

    def binding(self, node: ast.AST) -> tuple | None:
        return self.cm._resolve_expr_binding(node, self.sym.module, self.local_names)

    def _bind_params(self) -> None:
        node = self.sym.node
        args = node.args
        all_args = args.posonlyargs + args.args + args.kwonlyargs
        for a in all_args:
            self.params.append(a.arg)
            t = self.cm.ann_type(a.annotation, self.sym.module)
            if t:
                self.types[a.arg] = t
        if self.sym.cls and all_args and all_args[0].arg in ("self", "cls"):
            self.types[all_args[0].arg] = self.sym.cls

    # ----------------------------------------------------------------------- inference

    def infer(self) -> None:
        for _ in range(2):  # twice, so a name typed late in the body still types earlier-used names
            for node in iter_scope(self.body):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        self._assign(t, node.value)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    self.types[node.target.id] = self.cm.ann_type(node.annotation, self.sym.module) or (
                        self.type_of(node.value) if node.value else None
                    )
                    if node.value is not None:
                        self.values[node.target.id] = node.value
                elif isinstance(node, ast.NamedExpr):
                    self._assign(node.target, node.value)
                elif isinstance(node, ast.With):
                    for item in node.items:
                        if isinstance(item.optional_vars, ast.Name):
                            t = self.type_of(item.context_expr)
                            if isinstance(t, tuple) and t[0] == "list":
                                t = t[1]  # a @contextmanager yielding T
                            self.types[item.optional_vars.id] = t
                elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
                    t = self.type_of(node.iter)
                    if isinstance(t, tuple) and t[0] == "list":
                        self.types[node.target.id] = t[1]

    def _assign(self, target: ast.AST, value: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self.values[target.id] = value
            t = self.type_of(value)
            if t is not None or target.id not in self.types:
                self.types[target.id] = t
        elif isinstance(target, ast.Tuple):
            t = self.type_of(value)
            if isinstance(t, tuple) and t[0] == "ext":
                # col1, col2 = st.columns(2): every element is an object of that library.
                for i, el in enumerate(target.elts):
                    if isinstance(el, ast.Name):
                        self.types[el.id] = ("ext", f"{t[1]}[{i}]")
            if isinstance(t, tuple) and t[0] == "tuple":
                for el, et in zip(target.elts, t[1], strict=False):
                    if isinstance(el, ast.Name):
                        self.types[el.id] = et

    def type_of(self, node: ast.AST | None) -> Any:
        if node is None:
            return None
        if isinstance(node, ast.Name):
            if node.id in self.types:
                return self.types[node.id]
            b = self.lookup(node.id)
            if b and b[0] == "mod":
                return ("module", b[1])
            return None
        if isinstance(node, ast.BoolOp):
            for v in node.values:
                if t := self.type_of(v):
                    return t
            return None
        if isinstance(node, ast.IfExp):
            return self.type_of(node.body) or self.type_of(node.orelse)
        if isinstance(node, ast.Attribute):
            base = self.type_of(node.value)
            if isinstance(base, tuple) and base[0] == "module":
                b = self.cm.lookup(base[1], node.attr)
                if b and b[0] == "mod":
                    return ("module", b[1])
                return None
            if isinstance(base, str) and base != "@db":
                return self.cm.attr_type(base, node.attr)
            if isinstance(base, tuple) and base[0] == "ext":
                return ("ext", f"{base[1]}.{node.attr}")
            return None
        if isinstance(node, ast.Call):
            return self._call_type(node)
        if isinstance(node, ast.Subscript):
            t = self.type_of(node.value)
            if isinstance(t, tuple) and t[0] == "list":
                return t[1]
            if isinstance(t, tuple) and t[0] == "tuple" and isinstance(node.slice, ast.Constant):
                idx = node.slice.value
                return t[1][idx] if isinstance(idx, int) and idx < len(t[1]) else None
            return None
        return None

    def _call_type(self, call: ast.Call) -> Any:
        func = call.func
        # SQLModel queries: s.get(T, ...) -> T, s.exec(select(T)...).first() -> T, .all() -> list[T].
        if isinstance(func, ast.Attribute):
            if func.attr == "get" and self.type_of(func.value) == "@db" and call.args:
                t = self._table_of(call.args[0])
                if t:
                    return t
            if func.attr in ("first", "one", "all") and isinstance(func.value, ast.Call):
                inner = func.value
                if isinstance(inner.func, ast.Attribute) and inner.func.attr == "exec" and inner.args:
                    t = self._selected_table(inner.args[0])
                    if t:
                        return ("list", t) if func.attr == "all" else t
        targets, kind = self.resolve_func(func)
        if kind == "external":
            return ("ext", self.external_name(func) + "()")
        for target in targets:
            sym = self.cm.symbols[target]
            if sym.kind == "class":
                return target
            if sym.kind == "field":
                ft = self.cm.attr_type(sym.cls, sym.qualname.rsplit(".", 1)[1])
                return ft[1] if isinstance(ft, tuple) and ft[0] == "callable" else None
            return self.cm.return_type(target)
        return None

    def _table_of(self, node: ast.AST) -> str | None:
        b = self.binding(node)
        if b and b[0] == "sym" and b[1] in self.cm.tables:
            return b[1]
        return None

    def _selected_table(self, node: ast.AST) -> str | None:
        """The table of `select(T)` at the root of a query chain like select(T).where(...).order_by(...)."""
        while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            node = node.func.value
        if isinstance(node, ast.Call) and node.args and src(node.func).endswith("select"):
            return self._table_of(node.args[0])
        return None

    # ----------------------------------------------------------------------- resolution

    def resolve_func(self, func: ast.AST) -> tuple[list[str], str]:
        """-> ([symbol ids], category) where category is internal | external | builtin | unresolved."""
        if isinstance(func, ast.Name):
            if func.id in self.locals_fns:
                return [self.locals_fns[func.id]], "internal"
            if func.id in self.types or func.id in self.params:
                return [], "unresolved"  # a local variable or parameter holding a callable
            b = self.lookup(func.id)
            if b is None:
                return [], "builtin" if func.id in BUILTIN_NAMES else "unresolved"
            if b[0] == "sym":
                return [b[1]], "internal"
            if b[0] in ("ext", "extmod"):
                return [], "external"
            return [], "unresolved"
        if isinstance(func, ast.Attribute):
            base_t = self.type_of(func.value)
            if isinstance(base_t, tuple) and base_t[0] == "module":
                b = self.cm.lookup(base_t[1], func.attr)
                if b and b[0] == "sym":
                    return [b[1]], "internal"
                return [], "external" if b and b[0] == "ext" else "unresolved"
            if isinstance(base_t, str) and base_t != "@db":
                member = self.cm.find_member(base_t, func.attr)
                if member:
                    return [member], "internal"
                if self.cm.attr_type(base_t, func.attr) is not None or func.attr in self.cm.class_attrs.get(
                    base_t, {}
                ):
                    return [], "unresolved"  # an injected callable stored on the object (e.g. self.recorder)
                return [], "external"  # e.g. a pydantic or dataclass method on our own class
            if base_t == "@db" or (isinstance(base_t, tuple) and base_t[0] == "ext"):
                return [], "external"
            b = self.binding(func.value)
            if b and b[0] in ("ext", "extmod"):
                return [], "external"
            if b and b[0] == "const":
                # A module-level object such as `log = logging.getLogger(__name__)`.
                value = self.cm.modules[b[1]].consts.get(b[2])
                if isinstance(value, ast.Call):
                    vb = self.cm._resolve_expr_binding(value.func, b[1])
                    if vb and vb[0] in ("ext", "extmod"):
                        return [], "external"
                if isinstance(value, ast.Dict | ast.List | ast.Set | ast.Tuple | ast.Constant):
                    return [], "builtin"
            if b and b[0] == "sym" and self.cm.symbols[b[1]].kind == "class":
                member = self.cm.find_member(b[1], func.attr)
                return ([member], "internal") if member else ([], "external")
            if isinstance(func.value, ast.Constant | ast.JoinedStr | ast.List | ast.Dict | ast.Set):
                return [], "builtin"
            if func.attr in BUILTIN_METHODS:
                return [], "builtin"
            return [], "unresolved"
        return [], "unresolved"

    def external_name(self, func: ast.AST) -> str:
        if isinstance(func, ast.Attribute):
            base_t = self.type_of(func.value)
            if isinstance(base_t, tuple) and base_t[0] == "ext":
                return f"{base_t[1]}.{func.attr}"
        chain = attr_chain(func)
        if not chain:
            return src(func, 50)
        if self.type_of(ast.Name(chain[0])) == "@db" or self.types.get(chain[0]) == "@db":
            return "db." + ".".join(chain[1:])
        b = self.lookup(chain[0])
        if b and b[0] in ("ext", "extmod"):
            return ".".join([b[1], *chain[1:]])
        if b and b[0] == "const":
            value = self.cm.modules[b[1]].consts.get(b[2])
            if isinstance(value, ast.Call):
                return ".".join([src(value.func, 40) + "()", *chain[1:]])
        t = self.types.get(chain[0])
        if isinstance(t, str) and t != "@db":
            return ".".join([t.split(":")[1], *chain[1:]])
        return ".".join(chain)

    def builders_of(self, arg: ast.AST) -> set[str]:
        """Functions that produce a messages list: a direct call, or a local assigned from one."""
        if isinstance(arg, ast.Name) and arg.id in self.values:
            arg = self.values[arg.id]
        if isinstance(arg, ast.Call):
            targets, _ = self.resolve_func(arg.func)
            return set(targets)
        if isinstance(arg, ast.List):
            out = set()
            for el in arg.elts:
                if isinstance(el, ast.Starred):
                    out |= self.builders_of(el.value)
            return out
        return set()

    def const_strings(self, node: ast.AST, depth: int = 0) -> set[str]:
        if depth > 4 or node is None:
            return set()
        if s := const_str(node):
            return {s}
        if isinstance(node, ast.IfExp):
            return self.const_strings(node.body, depth + 1) | self.const_strings(node.orelse, depth + 1)
        if isinstance(node, ast.Name) and node.id in self.values:
            return self.const_strings(self.values[node.id], depth + 1)
        return set()

    def resolve(self) -> None:
        cm, sym = self.cm, self.sym
        count = not cm.modules[sym.module].is_test
        data = sym.data
        externals: set[str] = set()
        unresolved: list[dict] = []
        db: dict[str, set[str]] = {}
        roles: set[str] = set()
        templates: list[str] = []
        call_funcs = set()
        for node in iter_scope(self.body):
            if isinstance(node, ast.Call):
                call_funcs.add(id(node.func))
        for node in iter_scope(self.body):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values, strict=True):
                    if const_str(k) == "role":
                        roles |= self.const_strings(v)
            if isinstance(node, ast.Call):
                targets, category = self.resolve_func(node.func)
                if category == "internal":
                    cm.stats["resolved"] += count
                    for t in targets:
                        kind = "construct" if cm.symbols[t].kind == "class" else "call"
                        cm.add_edge(sym.id, t, kind, node.lineno)
                        if kind == "construct" and t in cm.tables:
                            db.setdefault(t, set()).add("write")
                        if kind == "construct":
                            self._bind_fields(t, node)
                    cm.call_sites.append({"caller": sym.id, "targets": targets, "node": node, "scope": self})
                    self._special_call(node, targets, templates)
                elif category == "external":
                    cm.stats["external"] += count
                    externals.add(self.external_name(node.func))
                elif category == "builtin":
                    cm.stats["builtin"] += count
                else:
                    cm.stats["unresolved"] += count
                    attr = node.func.attr if isinstance(node.func, ast.Attribute) else None
                    candidates = sorted(
                        s.id
                        for s in cm.symbols.values()
                        if attr
                        and s.kind in ("method", "property")
                        and s.qualname.endswith(f".{attr}")
                        and not cm.modules[s.module].is_test
                    )
                    unresolved.append(
                        {"text": src(node.func, 70), "line": node.lineno, "candidates": candidates}
                    )
                self._db_ops(node, db)
            elif isinstance(node, ast.Attribute | ast.Name) and id(node) not in call_funcs:
                self._reference(node)
            if isinstance(node, ast.Assign | ast.AugAssign):
                targets_ = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets_:
                    if isinstance(t, ast.Attribute):
                        tt = self.type_of(t.value)
                        if isinstance(tt, str) and tt in cm.tables:
                            db.setdefault(tt, set()).add("write")
        if externals:
            data["externals"] = sorted(externals)
        if unresolved:
            data["unresolved"] = unresolved
        if db:
            data["db"] = {cm.symbols[t].qualname: sorted(ops) for t, ops in sorted(db.items())}
        if roles:
            data["message_roles"] = roles
        if templates:
            data["templates"] = sorted(set(templates))

    def _reference(self, node: ast.AST) -> None:
        """A function used as a value (`submit(eng.retry, ...)`, `pool.map(one_run, ...)`), or a property."""
        cm = self.cm
        if isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load):
                return
            target = self.locals_fns.get(node.id)
            if target is None and node.id not in self.types and node.id not in self.params:
                b = self.lookup(node.id)
                target = b[1] if b and b[0] == "sym" else None
            if target and cm.symbols[target].kind in ("function", "nested", "method"):
                cm.add_edge(self.sym.id, target, "ref", node.lineno)
            return
        base_t = self.type_of(node.value)
        target = None
        if isinstance(base_t, tuple) and base_t[0] == "module":
            b = cm.lookup(base_t[1], node.attr)
            target = b[1] if b and b[0] == "sym" else None
        elif isinstance(base_t, str) and base_t != "@db":
            target = cm.find_member(base_t, node.attr)
        if target and cm.symbols[target].kind in ("function", "nested", "method", "property"):
            cm.add_edge(self.sym.id, target, "ref", node.lineno)

    def _bind_fields(self, cls_id: str, call: ast.Call) -> None:
        """`EngineDeps(make_llm=make_llm)`: the function passed in is what the field calls at run time."""
        for kw in call.keywords:
            fid = f"{cls_id}.{kw.arg}"
            if kw.arg and fid in self.cm.symbols and self.cm.symbols[fid].kind == "field":
                targets, _ = (
                    self.resolve_func(kw.value)
                    if isinstance(kw.value, ast.Name | ast.Attribute)
                    else ([], "")
                )
                for t in targets:
                    self.cm.add_edge(fid, t, "binds", call.lineno)

    def _db_ops(self, node: ast.Call, db: dict[str, set[str]]) -> None:
        func = node.func
        name = src(func, 60)
        if name.endswith("select") or (isinstance(func, ast.Attribute) and func.attr == "join"):
            for sub in ast.walk(ast.Module(body=[ast.Expr(a) for a in node.args], type_ignores=[])):
                if isinstance(sub, ast.Name | ast.Attribute):
                    t = self._table_of(sub)
                    if t:
                        db.setdefault(t, set()).add("read")
        if isinstance(func, ast.Attribute) and self.type_of(func.value) == "@db" and node.args:
            arg_t = self._table_of(node.args[0]) if func.attr == "get" else self.type_of(node.args[0])
            if func.attr == "get" and arg_t:
                db.setdefault(arg_t, set()).add("read")
            elif func.attr == "add" and isinstance(arg_t, str) and arg_t in self.cm.tables:
                db.setdefault(arg_t, set()).add("write")
            elif func.attr == "delete" and isinstance(arg_t, str) and arg_t in self.cm.tables:
                db.setdefault(arg_t, set()).add("delete")

    def _special_call(self, node: ast.Call, targets: list[str], templates: list[str]) -> None:
        cm = self.cm
        for t in targets:
            if t == "interview_app.interview.prompting:render" and node.args:
                names = template_names(node.args[0])
                templates.extend(names)
                cm.render_sites.append(
                    {
                        "symbol": self.sym.id,
                        "line": node.lineno,
                        "expr": src(node.args[0], 80),
                        "templates": names,
                        "kwargs": sorted(k.arg for k in node.keywords if k.arg),
                    }
                )
            # chat_json calling chat inside the gateway is not a separate model call site.
            inside_gateway = self.sym.id.startswith(
                ("interview_app.llm.client:", "interview_app.llm.decide:")
            )
            if t in GATEWAYS and not inside_gateway and not cm.modules[self.sym.module].is_test:
                cm.model_calls.append(self._model_call(node, GATEWAYS[t], t))

    def _model_call(self, node: ast.Call, api: str, gateway: str) -> dict:
        cm = self.cm
        kwargs: dict[str, ast.AST] = {}
        for k in node.keywords:
            if k.arg:
                kwargs[k.arg] = k.value
            elif isinstance(k.value, ast.Name) and isinstance(self.values.get(k.value.id), ast.Dict):
                d = self.values[k.value.id]  # `**call` where call = {"model": ..., ...}
                for dk, dv in zip(d.keys, d.values, strict=True):
                    if s := const_str(dk):
                        kwargs[s] = dv
        role = const_str(node.args[0]) if node.args else None
        model_expr = kwargs.get("model")
        mc: dict[str, Any] = {
            "site": self.sym.id,
            "line": node.lineno,
            "api": api,
            "gateway": gateway,
            "role": (role or src(node.args[0])) if node.args else None,
            "model_expr": src(model_expr) if model_expr is not None else None,
            "models_field": models_field(model_expr) if model_expr is not None else None,
            "settings": {k: src(kwargs[k]) for k in MODEL_SETTING_KWARGS if k in kwargs},
        }
        if mc["models_field"] is None:
            # No model passed: the gateway's own default (DecisionClient.decide uses settings.models.jev).
            gw = cm.symbols[gateway].node
            fields = {m for n in ast.walk(gw) if (m := models_field(n))} if gw else set()
            if len(fields) == 1:
                mc["models_field"] = fields.pop()
                mc["model_default_in_gateway"] = True
        mc["_builders"] = set()
        mc["_messages_param"] = None
        if api in ("chat", "chat_json") and len(node.args) > 1:
            msgs = node.args[1]
            mc["messages_expr"] = src(msgs, 90)
            if isinstance(msgs, ast.Name) and msgs.id in self.params and msgs.id not in self.values:
                mc["_messages_param"] = msgs.id
            else:
                mc["_builders"] = self.builders_of(msgs)
        if api == "chat_json" and len(node.args) > 2:
            mc["schema_expr"] = src(node.args[2])
            mc["schemas"] = self._schema_classes(node.args[2])
        if api == "decide":
            if len(node.args) > 1:
                mc["state_expr"] = src(node.args[1], 120)
                mc["state_keys"] = self._dict_keys(node.args[1])
            if len(node.args) > 2:
                mc["questions_expr"] = src(node.args[2], 120)
                mc["questions"] = self._questions(node.args[2], self.sym.module)
        return mc

    def _schema_classes(self, node: ast.AST) -> list[dict]:
        if isinstance(node, ast.Name) and node.id in self.values:
            value = self.values[node.id]
            if isinstance(value, ast.Subscript):
                # schema = TURN_SCHEMA[config.prompt_variant]: every class the dict can return.
                b = self.binding(value.value)
                if b and b[0] == "const":
                    d = self.cm.modules[b[1]].consts.get(b[2])
                    if isinstance(d, ast.Dict):
                        out = []
                        for k, v in zip(d.keys, d.values, strict=True):
                            vb = self.cm._resolve_expr_binding(v, b[1])
                            if vb and vb[0] == "sym":
                                out.append({"key": src(k), "class": vb[1], "via": src(value.value)})
                        return out
            node = value
        b = self.binding(node)
        if b and b[0] == "sym":
            return [{"key": None, "class": b[1]}]
        return []

    def _dict_keys(self, node: ast.AST) -> list[str]:
        if isinstance(node, ast.Name) and node.id in self.values:
            node = self.values[node.id]
        keys: list[str] = []
        if isinstance(node, ast.BinOp):  # {"a": 1} | {f"chunk_{i}": c ...}
            return self._dict_keys(node.left) + self._dict_keys(node.right)
        if isinstance(node, ast.Dict):
            keys = [const_str(k) or src(k) for k in node.keys if k is not None]
        elif isinstance(node, ast.DictComp):
            keys = [src(node.key) + " (per item)"]
        elif isinstance(node, ast.Call):
            targets, _ = self.resolve_func(node.func)
            for t in targets:
                fn = self.cm.symbols[t].node
                if fn is None:
                    continue
                for n in iter_scope(fn.body):
                    if isinstance(n, ast.AnnAssign | ast.Assign) and isinstance(n.value, ast.Dict):
                        keys += [const_str(k) for k in n.value.keys if const_str(k)]
                    if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript):
                        k = n.targets[0].slice
                        keys.append(const_str(k) or f"{src(k)} (dynamic)")
                keys = [k for k in dict.fromkeys(keys)]
                keys = [f"built by {self.cm.symbols[t].qualname}()", *keys]
        return keys

    def _questions(self, node: ast.AST, mod_id: str, depth: int = 0) -> list[dict]:
        """The Jev questions of a decide() call: name and type (noul / score / choice)."""
        cm = self.cm
        if depth > 5:
            return []
        if isinstance(node, ast.Name):
            if node.id in self.values and mod_id == self.sym.module:
                return self._questions(self.values[node.id], mod_id, depth + 1)
            b = cm.lookup(mod_id, node.id)
            if b and b[0] == "const":
                return self._questions(cm.modules[b[1]].consts[b[2]], b[1], depth + 1)
            return []
        if isinstance(node, ast.Call) and src(node.func) == "dict" and node.args:
            return self._questions(node.args[0], mod_id, depth + 1)
        out = []
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if k is None:
                    out += self._questions(v, mod_id, depth + 1)
                else:
                    out.append({"name": const_str(k) or src(k), "type": self._question_type(v, mod_id)})
        elif isinstance(node, ast.DictComp):
            out.append(
                {"name": src(node.key) + " (per item)", "type": self._question_type(node.value, mod_id)}
            )
        return out

    def _question_type(self, node: ast.AST, mod_id: str) -> str | None:
        if isinstance(node, ast.Call):
            b = (
                self.binding(node.func)
                if mod_id == self.sym.module
                else self.cm._resolve_expr_binding(node.func, mod_id)
            )
            if b and b[0] == "sym":
                cls = b[1] if self.cm.symbols[b[1]].kind == "class" else self.cm.return_type(b[1])
                if isinstance(cls, str):
                    return question_type_of(self.cm, cls)
        return None


def question_type_of(cm: CodeMap, cls_id: str) -> str | None:
    """Jev question classes declare `type: Literal["noul"] = "noul"`; read that default."""
    node = cm.symbols[cls_id].node
    for item in node.body if node else []:
        if isinstance(item, ast.AnnAssign) and getattr(item.target, "id", "") == "type":
            return const_str(item.value)
    return None


def models_field(node: ast.AST | None) -> str | None:
    """`deps.settings.models.interviewer` (anywhere in an expression) -> "interviewer".

    The TTS model lives in its own group (`settings.tts.model`, TTSSettings) and maps to "tts", as does
    `session_voice_model(...)` (voice.py: the session's picked TTS model, else `settings.tts.model`)."""
    if node is None:
        return None
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute) and n.value.attr == "models":
            return n.attr
        if isinstance(n, ast.Attribute) and n.attr == "model" and getattr(n.value, "attr", None) == "tts":
            return "tts"
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "session_voice_model":
            return "tts"
    return None


def template_names(node: ast.AST) -> list[str]:
    """`render("plan.md")` -> ["plan.md"]; `render(f"interviewer_{v}.md")` -> every matching file."""
    if s := const_str(node):
        return [s]
    if isinstance(node, ast.JoinedStr):
        pattern = "".join(re.escape(v.value) if isinstance(v, ast.Constant) else ".+" for v in node.values)
        return sorted(p.name for p in PROMPTS_DIR.glob("*.md") if re.fullmatch(pattern, p.name))
    return []


def layer_of(mod_id: str) -> str:
    if mod_id.startswith("app"):
        return "ui"
    if mod_id.startswith(("lab", "interview_app.lab")):
        return "lab"
    for prefix, layer in (
        ("interview_app.llm", "llm"),
        ("interview_app.security", "security"),
        ("interview_app.evaluation", "evaluation"),
    ):
        if mod_id.startswith(prefix):
            return layer
    if mod_id in ("interview_app", "interview_app.config", "interview_app.db"):
        return "foundation"
    return "core"


# --------------------------------------------------------------------------- templates


def parse_templates() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        text = path.read_text()
        comment = re.match(r"\s*\{#(.*?)#\}", text, re.S)
        includes = re.findall(r"\{%-?\s*include\s+[\"']([^\"']+)[\"']", text)
        loop_vars: set[str] = set()
        for targets in re.findall(r"\{%-?\s*for\s+(.+?)\s+in\s", text):
            loop_vars |= {t.strip() for t in targets.split(",")}
        variables: set[str] = set()
        for expr in re.findall(r"\{\{(.*?)\}\}|\{%(.*?)%\}", text, re.S):
            body = re.sub(r"\"[^\"]*\"|'[^']*'", "", expr[0] or expr[1])
            body = re.sub(r"\|\s*\w+", "", body)  # filters such as | join
            for name in re.findall(r"(?<![\w.])([A-Za-z_]\w*)", body):
                if name not in JINJA_WORDS and name not in loop_vars:
                    variables.add(name)
        out[path.name] = {
            "path": str(path.relative_to(ROOT)),
            "comment": unwrap(comment.group(1)) if comment else "",
            "includes": includes,
            "variables": sorted(variables),
            "lines": text.count("\n") + 1,
            "chars": len(text),
            "source": text,
        }
    for name, t in out.items():
        t["included_by"] = sorted(n for n, o in out.items() if name in o["includes"])
    return out


def all_variables(templates: dict, name: str, seen: set | None = None) -> set[str]:
    """Variables a template needs, including those of the templates it includes."""
    seen = seen or set()
    if name in seen or name not in templates:
        return set()
    seen.add(name)
    found = set(templates[name]["variables"])
    for inc in templates[name]["includes"]:
        found |= all_variables(templates, inc, seen)
    return found


# --------------------------------------------------------------------------- config + schemas


def extract_config(cm: CodeMap) -> dict:
    mod = cm.modules["interview_app.config"]
    lines = mod.source.split("\n")
    out = {}
    for node in mod.tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        fields = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                line = lines[item.lineno - 1]
                comment = line.split("  # ", 1)[1].strip() if "  # " in line else ""
                fields.append(
                    {
                        "name": item.target.id,
                        "type": src(item.annotation, 60),
                        "default": src(item.value, 100) if item.value is not None else None,
                        "comment": comment,
                        "line": item.lineno,
                    }
                )
        out[node.name] = {
            "doc": first_paragraph(ast.get_docstring(node)),
            "fields": fields,
            "line": node.lineno,
        }
    return out


def unread_config_fields(cm: CodeMap, config: dict) -> list[dict]:
    """Config fields whose attribute name never appears as `.name` outside config.py (likely unused)."""
    used: set[str] = set()
    for mod in cm.modules.values():
        if mod.id == "interview_app.config" or mod.is_test:
            continue
        for n in ast.walk(mod.tree):
            if isinstance(n, ast.Attribute):
                used.add(n.attr)
            elif isinstance(n, ast.keyword) and n.arg:
                used.add(n.arg)
    out = []
    for cls, info in config.items():
        for f in info["fields"]:
            if f["name"] not in used and cls not in ("ModelChoice",):
                out.append({"class": cls, "field": f["name"], "line": f["line"], "comment": f["comment"]})
    return out


def extract_schema(cm: CodeMap, sym: Symbol) -> dict:
    fields = []
    for item in sym.node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            desc = default = None
            v = item.value
            if isinstance(v, ast.Call) and src(v.func).endswith("Field"):
                for k in v.keywords:
                    if k.arg == "description":
                        desc = " ".join(const_str(k.value).split()) if const_str(k.value) else src(k.value)
                    if k.arg in ("default", "default_factory"):
                        default = src(k.value, 40)
            elif v is not None:
                default = src(v, 60)
            fields.append(
                {
                    "name": item.target.id,
                    "type": src(item.annotation, 80),
                    "description": desc,
                    "default": default,
                }
            )
    return {"fields": fields, "bases": [src(b) for b in sym.node.bases]}


# --------------------------------------------------------------------------- assembly


def signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(src(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    if isinstance(node, ast.AnnAssign):
        return f"{src(node.target)}: {src(node.annotation)}"
    args = ast.unparse(node.args)
    ret = f" -> {src(node.returns)}" if node.returns is not None else ""
    return f"{node.name}({args}){ret}"


AGENT_ORDER = ["interviewer", "planner", "judge", "candidate_sim", "guard", "live_score", "lab_judge", "tts"]


def config_path(models_field: str | None) -> str | None:
    """`Settings.models.<x>` for the RoleModels fields, `Settings.tts.model` for the TTS group."""
    if models_field is None:
        return None
    return "Settings.tts.model" if models_field == "tts" else f"Settings.models.{models_field}"


def build_agents(cm: CodeMap, edges: list[dict], config: dict) -> list[dict]:
    defaults = {f["name"]: f for f in config.get("RoleModels", {}).get("fields", [])}
    # TTSSettings.model is the "tts" role's default (see models_field).
    tts_model = next(
        (f for f in config.get("TTSSettings", {}).get("fields", []) if f["name"] == "model"), None
    )
    if tts_model:
        defaults["tts"] = tts_model
    callers_of: dict[str, set[str]] = {}
    for e in edges:
        if e["kind"] in ("call", "ref"):
            callers_of.setdefault(e["to"], set()).add(e["from"])
    groups: dict[str, list[dict]] = {}
    for mc in cm.model_calls:
        groups.setdefault(mc["role"] or "?", []).append(mc)
    agents = []
    for role in sorted(groups, key=lambda r: (AGENT_ORDER.index(r) if r in AGENT_ORDER else 99, r)):
        sites = groups[role]
        field_ = next((s["models_field"] for s in sites if s["models_field"]), None)
        schemas = []
        for s in sites:
            for sc in s.get("schemas", []):
                if sc not in schemas:
                    schemas.append(sc)
        questions = []
        for s in sites:
            for q in s.get("questions", []):
                if q not in questions:
                    questions.append(q)
        agents.append(
            {
                "role": role,
                "api": sorted({s["api"] for s in sites}),
                "models_field": field_,
                # The real settings path for the page label: TTS has its own group, the rest use RoleModels.
                "config_path": config_path(field_),
                "default_model": (defaults.get(field_) or {}).get("default", "").strip("'\"")
                if field_
                else None,
                "model_comment": (defaults.get(field_) or {}).get("comment") if field_ else None,
                "sites": [{k: v for k, v in s.items() if k not in ("schemas", "questions")} for s in sites],
                "schemas": schemas,
                "questions": questions,
                "templates": sorted({t for s in sites for t in s.get("templates", [])}),
                "message_roles": sorted({r for s in sites for r in s.get("message_roles", [])}),
                "callers": sorted({c for s in sites for c in callers_of.get(s["site"], set())}),
            }
        )
    return agents


def build(root: Path = ROOT) -> dict:
    cm = CodeMap(root)
    cm.discover()
    cm.collect_symbols()
    cm.bind_names()
    cm.collect_class_attrs()
    cm.analyse()

    edges = [
        {"from": a, "to": b, "kind": kind, "lines": sorted(lines)}
        for (a, b, kind), lines in sorted(cm.edges.items())
    ]
    test_edges = [e for e in edges if cm.modules[cm.symbols[e["from"]].module].is_test]
    edges = [
        e
        for e in edges
        if not cm.modules[cm.symbols[e["from"]].module].is_test
        and not cm.modules[cm.symbols[e["to"]].module].is_test
    ]
    tested_by: dict[str, set[str]] = {}
    for e in test_edges:
        tested_by.setdefault(e["to"], set()).add(cm.symbols[e["from"]].module)

    modules_out: dict[str, dict] = {}
    for mod in sorted(cm.modules.values(), key=lambda m: m.id):
        if mod.is_test:
            continue
        doc = ast.get_docstring(mod.tree) or ""
        rest = re.split(r"\n\s*\n", doc.strip(), maxsplit=1)
        modules_out[mod.id] = {
            "path": mod.path,
            "layer": mod.layer,
            "doc": first_paragraph(doc),
            "doc_more": unwrap(rest[1]) if len(rest) > 1 else "",
            "lines": mod.source.count("\n") + 1,
            "imports": sorted(i for i in mod.imports if i != mod.id and not cm.modules[i].is_test),
            "external_imports": sorted(mod.external_imports),
            "symbols": [],
        }
    for mod_id, info in modules_out.items():
        info["imported_by"] = sorted(m for m, o in modules_out.items() if mod_id in o["imports"])

    inbound: dict[str, set[str]] = {}
    for e in edges:
        inbound.setdefault(e["to"], set()).add(e["kind"])
    # An unresolved `x.name(...)` may well call any method with that name; such methods are not
    # reported as unreferenced (they are listed as candidates instead of being drawn as edges).
    for sym in cm.symbols.values():
        if not cm.modules[sym.module].is_test:
            for u in sym.data.get("unresolved", []):
                for cand in u["candidates"]:
                    inbound.setdefault(cand, set()).add("candidate")

    symbols_out: dict[str, dict] = {}
    schemas: dict[str, dict] = {}
    for sid in sorted(cm.symbols):
        sym = cm.symbols[sid]
        if cm.modules[sym.module].is_test:
            continue
        if sym.kind == "module" and not any(e["from"] == sid for e in edges) and "db" not in sym.data:
            continue
        node = sym.node
        doc = (
            ast.get_docstring(node)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            else None
        )
        out: dict[str, Any] = {
            "module": sym.module,
            "name": sym.qualname.rsplit(".", 1)[-1],
            "qualname": sym.qualname,
            "kind": sym.kind,
            "line": getattr(node, "lineno", 1),
            "end_line": getattr(node, "end_lineno", None) or getattr(node, "lineno", 1),
            "signature": signature(node) if node is not None else "module-level code",
            "doc": first_paragraph(doc),
        }
        if sym.cls:
            out["class"] = sym.cls
        if sym.parent:
            out["parent"] = sym.parent
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.decorator_list:
            out["decorators"] = [src(d, 60) for d in node.decorator_list]
        for key in ("externals", "unresolved", "db", "templates", "aliases"):
            if key in sym.data:
                out[key] = sym.data[key]
        if "message_roles" in sym.data:
            out["message_roles"] = sorted(sym.data["message_roles"])
        if sid in tested_by:
            out["tested_by"] = sorted(tested_by[sid])
        if sym.kind == "class":
            is_model = any(
                src(b).split(".")[-1] in ("BaseModel", "SQLModel", "BaseSettings") for b in node.bases
            )
            if is_model or sid in cm.tables:
                schemas[sid] = extract_schema(cm, sym)
                out["schema"] = True
            if sid in cm.tables:
                out["table"] = True
        symbols_out[sid] = out
        modules_out[sym.module]["symbols"].append(sid)

    model_calls = sorted(cm.model_calls, key=lambda m: (m["site"], m["line"]))
    for mc in model_calls:
        symbols_out[mc["site"]].setdefault("model_roles", [])
        if mc["role"] not in symbols_out[mc["site"]]["model_roles"]:
            symbols_out[mc["site"]]["model_roles"].append(mc["role"])

    templates = parse_templates()
    for rs in cm.render_sites:
        for name in rs["templates"]:
            if name not in templates:
                continue
            t = templates[name]
            t.setdefault("rendered_by", [])
            needed = all_variables(templates, name)
            t["rendered_by"].append(
                {
                    "symbol": rs["symbol"],
                    "line": rs["line"],
                    "expr": rs["expr"],
                    "unused_kwargs": sorted(set(rs["kwargs"]) - needed),
                    "missing_vars": sorted(needed - set(rs["kwargs"])),
                }
            )
    for t in templates.values():
        t["rendered_by"] = sorted(t.get("rendered_by", []), key=lambda r: (r["symbol"], r["line"]))

    tables = {}
    db_mod = cm.modules["interview_app.db"]
    for cid in sorted(cm.tables):
        sym = cm.symbols[cid]
        fks = []
        for item in sym.node.body:
            if isinstance(item, ast.AnnAssign):
                text = src(item.value, 300) if item.value is not None else ""
                m = re.search(r"foreign_key=['\"]([\w.]+)['\"]", text) or re.search(
                    r"ForeignKey\(['\"]([\w.]+)['\"]", text
                )
                if m:
                    fks.append(
                        {"field": src(item.target), "references": m.group(1), "cascade": "CASCADE" in text}
                    )
        ops: dict[str, list[str]] = {"read": [], "write": [], "delete": []}
        for sid, s in symbols_out.items():
            for op in s.get("db", {}).get(sym.qualname, []):
                ops[op].append(sid)
        tables[sym.qualname] = {
            "symbol": cid,
            "doc": first_paragraph(ast.get_docstring(sym.node)),
            "line": sym.node.lineno,
            "path": db_mod.path,
            "foreign_keys": fks,
            "readers": ops["read"],
            "writers": ops["write"],
            "deleters": ops["delete"],
        }

    config = extract_config(cm)
    agents = build_agents(cm, edges, config)

    # Functions nothing in the app or lab refers to. Entry points (module code, lab mains, dunder methods,
    # decorated framework hooks) are excluded; the rest are candidates to review, not proven dead code.
    unreferenced, test_only = [], []
    for sid, s in symbols_out.items():
        if s["kind"] not in ("function", "method", "nested", "property") or sid in inbound:
            continue
        if (
            s["name"].startswith("__")
            or s.get("decorators")
            or (s["module"].startswith("lab.") and s["name"] == "main")
        ):
            continue
        (test_only if s.get("tested_by") else unreferenced).append(sid)

    digest = hashlib.sha256()
    for mod in sorted(cm.modules.values(), key=lambda m: m.path):
        if not mod.is_test:
            digest.update(mod.path.encode() + b"\0" + mod.source.encode())
    for t in sorted(templates):
        digest.update(t.encode() + b"\0" + templates[t]["source"].encode())

    kinds = [s["kind"] for s in symbols_out.values()]
    edge_kinds = {k: sum(1 for e in edges if e["kind"] == k) for k in ("call", "ref", "construct", "binds")}
    return {
        "about": "Generated by reports/tools/build_code_map.py from the source code (static analysis). "
        "Do not edit by hand.",
        "source_sha256": digest.hexdigest(),
        "layers": [{"id": i, "label": label} for i, label in LAYERS],
        "stats": {
            "modules": len(modules_out),
            "functions": sum(k in ("function", "method", "nested", "property") for k in kinds),
            "classes": kinds.count("class"),
            "edges": edge_kinds,
            "call_sites": dict(cm.stats),
            "templates": len(templates),
            "model_call_sites": len(model_calls),
            "agents": len(agents),
            "tables": len(tables),
            "unresolved_listed": sum(len(s.get("unresolved", [])) for s in symbols_out.values()),
        },
        "modules": modules_out,
        "symbols": symbols_out,
        "edges": edges,
        "templates": templates,
        "model_calls": model_calls,
        "agents": agents,
        "schemas": schemas,
        "tables": tables,
        "config": config,
        "unread_config_fields": unread_config_fields(cm, config),
        "unreferenced": sorted(unreferenced),
        "test_only": sorted(test_only),
    }


def write_json(data: dict, path: Path = OUT_JSON) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json-only", action="store_true", help="skip building the HTML report")
    args = parser.parse_args(argv)
    data = build()
    write_json(data)
    s = data["stats"]
    calls = s["call_sites"]
    print(
        f"code_map.json: {s['modules']} modules, {s['functions']} functions, {s['classes']} classes, "
        f"edges {s['edges']}, call sites resolved={calls['resolved']} external={calls['external']} "
        f"builtin={calls['builtin']} unresolved={calls['unresolved']}, {s['agents']} model roles"
    )
    if not args.json_only:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_code_flow_html

        build_code_flow_html.main([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
