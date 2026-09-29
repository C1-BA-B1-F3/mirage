import json
import re
from typing import Any

from mirage.accessor.langfuse import LangfuseAccessor
from mirage.commands.builtin.grep_pattern import compile_pattern
from mirage.commands.builtin.grep_pushdown import grep_search_options
from mirage.core.hierarchy.scope import ScopeMatch
from mirage.core.hierarchy.search import Searcher
from mirage.core.langfuse.client import (fetch_datasets, fetch_prompts,
                                         fetch_sessions, fetch_traces)
from mirage.core.langfuse.scope import SEARCH_KINDS
from mirage.vfs.types import SearchQuery


def _compiled(query: SearchQuery) -> re.Pattern[str]:
    options = grep_search_options(query)
    return compile_pattern(query.query, options.ignore_case,
                           options.fixed_string, options.whole_word)


def _filter_traces(traces: list[dict[str, Any]],
                   pattern: re.Pattern[str]) -> list[str]:
    lines: list[str] = []
    for t in traces:
        trace_id = t.get("id", "")
        line_json = json.dumps(t, ensure_ascii=False, separators=(",", ":"))
        if not pattern.search(line_json):
            continue
        lines.append(f"traces/{trace_id}.json:{line_json}")
    return lines


def _filter_sessions(sessions: list[dict[str, Any]],
                     pattern: re.Pattern[str]) -> list[str]:
    lines: list[str] = []
    for s in sessions:
        session_id = s.get("id", "")
        if not pattern.search(session_id):
            continue
        line_json = json.dumps(s, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"sessions/{session_id}:{line_json}")
    return lines


def _filter_prompts(prompts: list[dict[str, Any]],
                    pattern: re.Pattern[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for p in prompts:
        prompt_name = p.get("name", "")
        if prompt_name in seen:
            continue
        if not pattern.search(prompt_name):
            continue
        seen.add(prompt_name)
        line_json = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"prompts/{prompt_name}:{line_json}")
    return lines


def _filter_datasets(datasets: list[dict[str, Any]],
                     pattern: re.Pattern[str]) -> list[str]:
    lines: list[str] = []
    for d in datasets:
        dataset_name = d.get("name", "")
        if not pattern.search(dataset_name):
            continue
        line_json = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"datasets/{dataset_name}:{line_json}")
    return lines


# The search push-down answers from the list endpoints (one call instead
# of one read per entry), so it greps listing summaries: a pattern that
# only occurs in a trace's observation bodies needs a file read to match.
async def _traces_searcher(accessor: LangfuseAccessor, match: ScopeMatch,
                           query: SearchQuery) -> list[str]:
    traces = await fetch_traces(accessor.api,
                                limit=accessor.config.default_search_limit)
    return _filter_traces(traces, _compiled(query))


async def _sessions_searcher(accessor: LangfuseAccessor, match: ScopeMatch,
                             query: SearchQuery) -> list[str]:
    sessions = await fetch_sessions(accessor.api,
                                    limit=accessor.config.default_search_limit)
    return _filter_sessions(sessions, _compiled(query))


async def _prompts_searcher(accessor: LangfuseAccessor, match: ScopeMatch,
                            query: SearchQuery) -> list[str]:
    return _filter_prompts(await fetch_prompts(accessor.api), _compiled(query))


async def _datasets_searcher(accessor: LangfuseAccessor, match: ScopeMatch,
                             query: SearchQuery) -> list[str]:
    return _filter_datasets(await fetch_datasets(accessor.api),
                            _compiled(query))


_CONTAINERS: dict[str, Searcher[LangfuseAccessor]] = {
    "traces": _traces_searcher,
    "sessions": _sessions_searcher,
    "prompts": _prompts_searcher,
    "datasets": _datasets_searcher,
}

SEARCHERS: dict[str, Searcher[LangfuseAccessor]] = {
    kind: _CONTAINERS[container]
    for kind, container in SEARCH_KINDS.items()
}
