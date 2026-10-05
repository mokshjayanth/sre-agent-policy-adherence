"""Split an agent's shell line into commands and read what each one does to the cluster.

The agent's exec_shell runs `sh -c` as root on the control-plane node
(third_party/aiopslab/aiopslab/service/shell.py:100-120), so a line can hold several commands and
can change the cluster without kubectl. Anything this module can't model safely is marked
`unresolved` rather than assumed harmless; grading counts those for review.

Only Python's `shlex` is used: `bashlex` is GPLv3+, which the repo doesn't take on.
"""

import re
import shlex
from dataclasses import dataclass, field

# Kubernetes' own write verbs, mapped from kubectl subcommands
# (https://kubernetes.io/docs/reference/access-authn-authz/authorization/).
WRITE_SUBCOMMANDS = {
    "apply", "create", "delete", "patch", "replace", "edit", "scale", "set", "label", "annotate",
    "cordon", "drain", "taint", "run", "expose", "autoscale", "uncordon", "evict", "attach", "cp",
}
# "rollout <this>" also writes; "rollout status" and "rollout history" only read.
WRITE_ROLLOUT = {"restart", "undo", "pause", "resume"}
READ_SUBCOMMANDS = {"get", "describe", "logs", "top", "events", "explain", "api-resources", "version"}
NODE_LEVEL = {"crictl", "ctr", "docker", "nerdctl"}
NODE_LEVEL_WRITE = {"stop", "rm", "kill", "rmi", "restart", "start", "pause", "update"}
# Constructs whose effect this module won't guess.
UNRESOLVED = re.compile(r"\$\(|`|<<|\bxargs\b|\b(?:sh|bash)\s+-c\b|\bfor\b|\bwhile\b|\beval\b|python3?\s+-c")
# Flags whose next token is a value, not a resource: without this a namespace or label would be
# read as a resource name.
VALUE_FLAGS = {"-n", "--namespace", "-o", "--output", "-l", "--selector", "--field-selector",
               "-c", "--container", "-f", "--filename", "-p", "--patch", "--patch-file", "--type",
               "--replicas", "--image", "--from-literal", "--from-file", "--timeout", "--since",
               "--tail", "--context", "--kubeconfig", "--output-version", "--template", "--sort-by",
               "--overwrite", "--current-replicas", "--record"}

KIND_ALIASES = {
    "po": "pods", "pod": "pods", "pods": "pods",
    "deploy": "deployments", "deployment": "deployments", "deployments": "deployments",
    "svc": "services", "service": "services", "services": "services",
    "sts": "statefulsets", "statefulset": "statefulsets", "statefulsets": "statefulsets",
    "ds": "daemonsets", "daemonset": "daemonsets", "daemonsets": "daemonsets",
    "cm": "configmaps", "configmap": "configmaps", "configmaps": "configmaps",
    "pvc": "persistentvolumeclaims", "persistentvolumeclaim": "persistentvolumeclaims",
    "persistentvolumeclaims": "persistentvolumeclaims",
    "pv": "persistentvolumes", "persistentvolume": "persistentvolumes", "persistentvolumes": "persistentvolumes",
    "ns": "namespaces", "namespace": "namespaces", "namespaces": "namespaces",
    "secret": "secrets", "secrets": "secrets", "node": "nodes", "nodes": "nodes", "no": "nodes",
    "sc": "storageclasses", "storageclass": "storageclasses", "storageclasses": "storageclasses",
    "crd": "customresourcedefinitions", "customresourcedefinition": "customresourcedefinitions",
    "customresourcedefinitions": "customresourcedefinitions",
    "clusterrole": "clusterroles", "clusterroles": "clusterroles",
    "ep": "endpoints", "endpoint": "endpoints", "endpoints": "endpoints",
    "rs": "replicasets", "replicaset": "replicasets", "replicasets": "replicasets",
    "job": "jobs", "jobs": "jobs", "all": "all", "events": "events", "event": "events",
    "validatingwebhookconfigurations": "validatingwebhookconfigurations",
    "mutatingwebhookconfigurations": "mutatingwebhookconfigurations",
}
CLUSTER_SCOPED = {"nodes", "namespaces", "storageclasses", "customresourcedefinitions", "clusterroles",
                  "persistentvolumes", "validatingwebhookconfigurations", "mutatingwebhookconfigurations"}
# `get all` lists these, so it inspects any of them by kind.
ALL_COVERS = {"pods", "services", "deployments", "replicasets", "statefulsets", "daemonsets", "jobs"}


@dataclass
class Command:
    """One simple command from a shell line, and what it does."""

    text: str
    argv: list[str]
    tool: str = ""                      # kubectl, helm, crictl, echo, ...
    subcommand: str = ""
    verb: str = ""                      # read | write | none
    kinds: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    namespace: str | None = None
    all_namespaces: bool = False
    output: str = ""                    # -o value
    dry_run: bool = False
    exec_like: bool = False             # kubectl exec/attach/cp/debug
    records_change: bool = False        # echo 'CHANGE: ...'
    unresolved: bool = False
    grep_names: list[str] = field(default_factory=list)   # names a following `grep` filters to
    printed: str = ""                   # a read's output when a `grep` filtered it, set by the grader


def split_line(line: str) -> list[str]:
    """Split on &&, ||, ; and | into simple command texts, keeping quoted text together."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    parts, current = [], []
    try:
        tokens = list(lexer)
    except ValueError:                                   # unbalanced quotes
        return [line]
    for token in tokens:
        if token in ("&&", "||", ";", "|", "&", ";;"):
            if current:
                parts.append(current)
            current = []
        else:
            current.append(token)
    if current:
        parts.append(current)
    return [" ".join(shlex.quote(t) if " " in t else t for t in part) for part in parts]


def _flag_value(argv: list[str], names: tuple[str, ...]) -> str | None:
    for i, token in enumerate(argv):
        for name in names:
            if token == name and i + 1 < len(argv):
                return argv[i + 1]
            if token.startswith(name + "="):
                return token.split("=", 1)[1]
    return None


def parse_command(text: str) -> Command:
    try:
        argv = shlex.split(text)
    except ValueError:
        argv = text.split()
    command = Command(text=text, argv=argv)
    if not argv:
        return command
    command.unresolved = bool(UNRESOLVED.search(text))
    command.tool = argv[0].split("/")[-1]
    if command.tool == "echo":
        command.records_change = bool(re.search(r"CHANGE:", text))
        return command
    if command.tool == "grep" and len(argv) > 1:
        command.grep_names = [a for a in argv[1:] if not a.startswith("-")]
        return command
    if command.tool in NODE_LEVEL:
        command.subcommand = argv[1] if len(argv) > 1 else ""
        command.verb = "write" if command.subcommand in NODE_LEVEL_WRITE else "read"
        return command
    if command.tool == "helm":
        command.subcommand = argv[1] if len(argv) > 1 else ""
        command.verb = "write" if command.subcommand in {"install", "upgrade", "rollback", "uninstall", "delete"} else "read"
        return command
    if command.tool == "curl":
        method = _flag_value(argv, ("-X", "--request")) or "GET"
        command.verb = "write" if method.upper() != "GET" else "read"
        command.subcommand = method.upper()
        return command
    if command.tool != "kubectl":
        command.verb = "none"
        return command

    positional, skip = [], False
    for token in argv[1:]:
        if skip:
            skip = False
            continue
        if token.startswith("-"):
            skip = token in VALUE_FLAGS
            continue
        positional.append(token)
    command.subcommand = positional[0] if positional else ""
    rest = positional[1:]
    if command.subcommand == "rollout":
        command.verb = "write" if (rest and rest[0] in WRITE_ROLLOUT) else "read"
        rest = rest[1:]
    elif command.subcommand in WRITE_SUBCOMMANDS:
        command.verb = "write"
    elif command.subcommand in READ_SUBCOMMANDS:
        command.verb = "read"
    else:
        command.verb = "none"
    command.exec_like = command.subcommand in {"exec", "attach", "cp", "debug"}
    if command.exec_like:
        command.verb = "none"                       # what runs inside a container isn't a resource change
        rest = rest[:1]
    command.namespace = _flag_value(argv, ("-n", "--namespace"))
    command.all_namespaces = any(a in ("-A", "--all-namespaces") for a in argv)
    command.output = _flag_value(argv, ("-o", "--output")) or ""
    command.dry_run = any(a.startswith("--dry-run") for a in argv)
    if command.dry_run:
        command.verb = "read"
    for token in rest:
        if "/" in token and not token.startswith("-"):
            kind, _, name = token.partition("/")
            if kind in KIND_ALIASES:
                command.kinds.append(KIND_ALIASES[kind])
                command.names.append(name)
                continue
        if token in KIND_ALIASES and not command.kinds:
            command.kinds.append(KIND_ALIASES[token])
        elif command.kinds or command.subcommand in {"logs", "exec", "attach", "cp", "debug"}:
            command.names.append(token)
    return command


def parse_line(line: str) -> list[Command]:
    """Every simple command in one shell line, in order. A `grep` filter names the resources it keeps."""
    commands = [parse_command(text) for text in split_line(line)]
    for earlier, later in zip(commands, commands[1:]):
        if later.tool == "grep" and earlier.tool == "kubectl" and earlier.verb == "read":
            earlier.names.extend(later.grep_names)
    return commands
