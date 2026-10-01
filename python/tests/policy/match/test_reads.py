# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

from mirage.policy.match import has_rules, reads_args, scopes_paths
from mirage.policy.types import AdmissionRules, CommandRule


def test_has_rules_is_a_role_stating_anything():
    assert not has_rules(None)
    assert not has_rules(AdmissionRules())
    assert has_rules(AdmissionRules(allow=()))
    assert has_rules(AdmissionRules(ask=(CommandRule("r"),)))
    assert has_rules(AdmissionRules(deny=(CommandRule("r"),)))


def test_reads_args_only_for_a_rule_that_reads_past_the_name():
    rules = AdmissionRules(
        allow=("cat", "git status", "*"),
        deny=(
            CommandRule("no rm", commands=("rm",)),
            CommandRule("sealed", commands=("cat",), paths=("/secret*",)),
            CommandRule("no force", commands=("git push -f",)),
            CommandRule("repo", commands=("ls",), mount="/repo"),
        ),
        ask=(CommandRule("frozen", paths=("/locked/*",)),),
    )
    # A token after the name, a path or a mount reads the arguments.
    assert reads_args(rules, "git")
    assert reads_args(rules, "cat")
    assert reads_args(rules, "ls")
    # The command-less frozen rule reads every command's paths.
    assert reads_args(rules, "echo")
    # With no such rule for it, a command's arguments are unread: the
    # wildcard allow and the bare `rm` deny decide on the name alone.
    assert not reads_args(
        AdmissionRules(
            allow=("*", "rm"), deny=(CommandRule("no rm", commands=("rm",)),)
        ),
        "rm",
    )
    assert not reads_args(None, "rm")


def test_scopes_paths_is_a_path_rule_that_applies_to_this_command():
    named = AdmissionRules(
        deny=(
            CommandRule("no rm", commands=("rm",)),
            CommandRule("sealed", commands=("cat",), paths=("/secret*",)),
            CommandRule("repo", commands=("ls",), mount="/repo"),
        )
    )
    # A glob operand of cat or ls must be expanded before the gate reads
    # it: a rule names the command and reads its paths (or its mount).
    assert scopes_paths(named, "cat")
    assert scopes_paths(named, "ls")
    # The bare rm deny and an allow list read the name alone.
    assert not scopes_paths(
        AdmissionRules(allow=("rm", "*"), deny=named.deny), "rm"
    )
    assert not scopes_paths(named, "echo")
    assert not scopes_paths(None, "cat")
    # A pure path rule applies to every command, so every command's globs
    # expand: a pattern that only later matches under the scope would
    # otherwise reach the command unjudged.
    frozen = CommandRule("frozen", paths=("/locked/*",))
    assert scopes_paths(AdmissionRules(deny=named.deny, ask=(frozen,)), "rm")
    assert scopes_paths(AdmissionRules(ask=(frozen,)), "echo")
