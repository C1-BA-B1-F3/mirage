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

import re

SEARCH_FLAGS = {
    'issues': [
        'app', 'archived', 'assignee', 'author', 'closed', 'commenter',
        'comments', 'created', 'interactions', 'involves', 'label', 'language',
        'locked', 'match', 'mentions', 'milestone', 'no-assignee', 'no-label',
        'no-milestone', 'no-project', 'owner', 'project', 'reactions', 'repo',
        'state', 'team-mentions', 'updated', 'visibility', 'include-prs'
    ],
    'prs': [
        'app', 'archived', 'assignee', 'author', 'closed', 'commenter',
        'comments', 'created', 'interactions', 'involves', 'label', 'language',
        'locked', 'match', 'mentions', 'milestone', 'no-assignee', 'no-label',
        'no-milestone', 'no-project', 'owner', 'project', 'reactions', 'repo',
        'state', 'team-mentions', 'updated', 'visibility', 'base', 'checks',
        'draft', 'head', 'merged', 'merged-at', 'review', 'review-requested',
        'reviewed-by'
    ],
    'repos': [
        'archived', 'created', 'followers', 'forks', 'good-first-issues',
        'help-wanted-issues', 'include-forks', 'language', 'license', 'match',
        'number-topics', 'owner', 'size', 'stars', 'topic', 'updated',
        'visibility'
    ],
    'code':
    ['extension', 'filename', 'language', 'match', 'owner', 'repo', 'size'],
    'commits': [
        'author', 'author-date', 'author-email', 'author-name', 'committer',
        'committer-date', 'committer-email', 'committer-name', 'hash', 'merge',
        'owner', 'parent', 'repo', 'tree', 'visibility'
    ]
}
SEARCH_MULTIPLE = [
    'label', 'match', 'owner', 'repo', 'visibility', 'license', 'topic'
]
SEARCH_BOOLEAN = [
    'archived', 'draft', 'merge', 'locked', 'merged', 'include-prs',
    'no-assignee', 'no-label', 'no-milestone', 'no-project'
]
SEARCH_ALIASES = {
    'owner': 'user',
    'match': 'in',
    'visibility': 'is',
    'team-mentions': 'team',
    'checks': 'status',
    'merged-at': 'merged',
    'number-topics': 'topics',
    'include-forks': 'fork'
}
SEARCH_SORTS = {
    'issues': [
        'comments', 'created', 'interactions', 'reactions', 'reactions-+1',
        'reactions--1', 'reactions-heart', 'reactions-smile', 'reactions-tada',
        'reactions-thinking_face', 'updated'
    ],
    'prs': [
        'comments', 'created', 'interactions', 'reactions', 'reactions-+1',
        'reactions--1', 'reactions-heart', 'reactions-smile', 'reactions-tada',
        'reactions-thinking_face', 'updated'
    ],
    'repos': ['forks', 'help-wanted-issues', 'stars', 'updated'],
    'commits': ['author-date', 'committer-date']
}
SEARCH_FIELDS = {
    'issues': [
        'assignees', 'author', 'authorAssociation', 'body', 'closedAt',
        'commentsCount', 'createdAt', 'id', 'isLocked', 'isPullRequest',
        'labels', 'number', 'repository', 'state', 'title', 'updatedAt', 'url'
    ],
    'prs': [
        'assignees', 'author', 'authorAssociation', 'body', 'closedAt',
        'commentsCount', 'createdAt', 'id', 'isLocked', 'isPullRequest',
        'labels', 'number', 'repository', 'state', 'title', 'updatedAt', 'url',
        'isDraft'
    ],
    'repos': [
        'createdAt', 'defaultBranch', 'description', 'forksCount', 'fullName',
        'hasDownloads', 'hasIssues', 'hasPages', 'hasProjects', 'hasWiki',
        'homepage', 'id', 'isArchived', 'isDisabled', 'isFork', 'isPrivate',
        'language', 'license', 'name', 'openIssuesCount', 'owner', 'pushedAt',
        'size', 'stargazersCount', 'updatedAt', 'url', 'visibility',
        'watchersCount'
    ],
    'code': ['path', 'repository', 'sha', 'textMatches', 'url'],
    'commits': [
        'author', 'commit', 'committer', 'sha', 'id', 'parents', 'repository',
        'url'
    ]
}
SEARCH_SHAPES = {
    'Repository': [['createdAt', 'created_at', 'time.Time'],
                   ['defaultBranch', 'default_branch', 'string'],
                   ['description', 'description', 'string'],
                   ['forksCount', 'forks_count', 'int'],
                   ['fullName', 'full_name', 'string'],
                   ['hasDownloads', 'has_downloads', 'bool'],
                   ['hasIssues', 'has_issues', 'bool'],
                   ['hasPages', 'has_pages', 'bool'],
                   ['hasProjects', 'has_projects', 'bool'],
                   ['hasWiki', 'has_wiki', 'bool'],
                   ['homepage', 'homepage', 'string'],
                   ['id', 'node_id', 'string'],
                   ['isArchived', 'archived', 'bool'],
                   ['isDisabled', 'disabled', 'bool'],
                   ['isFork', 'fork', 'bool'],
                   ['isPrivate', 'private', 'bool'],
                   ['language', 'language', 'string'],
                   ['license', 'license', 'License'],
                   ['masterBranch', 'master_branch', 'string'],
                   ['name', 'name', 'string'],
                   ['openIssuesCount', 'open_issues_count', 'int'],
                   ['owner', 'owner', 'User'],
                   ['pushedAt', 'pushed_at', 'time.Time'],
                   ['size', 'size', 'int'],
                   ['stargazersCount', 'stargazers_count', 'int'],
                   ['url', 'html_url', 'string'],
                   ['updatedAt', 'updated_at', 'time.Time'],
                   ['visibility', 'visibility', 'string'],
                   ['watchersCount', 'watchers_count', 'int']],
    'User': [['gravatarID', 'gravatar_id', 'string'],
             ['id', 'node_id', 'string'], ['login', 'login', 'string'],
             ['siteAdmin', 'site_admin', 'bool'], ['type', 'type', 'string'],
             ['url', 'html_url', 'string']],
    'CommitInfo': [['author', 'author', 'CommitUser'],
                   ['commentCount', 'comment_count', 'int'],
                   ['committer', 'committer', 'CommitUser'],
                   ['message', 'message', 'string'], ['tree', 'tree', 'Tree']],
    'CommitUser': [['date', 'date', 'time.Time'], ['email', 'email', 'string'],
                   ['name', 'name', 'string']],
    'Tree': [['sha', 'sha', 'string']],
    'Parent': [['sha', 'sha', 'string'], ['url', 'html_url', 'string']],
    'License': [['key', 'key', 'string'], ['name', 'name', 'string'],
                ['url', 'url', 'string']],
    'Label': [['color', 'color', 'string'],
              ['description', 'description', 'string'],
              ['id', 'node_id', 'string'], ['name', 'name', 'string']],
    'Issue': [['assignees', 'assignees', '[]User'], ['author', 'user', 'User'],
              ['authorAssociation', 'author_association', 'string'],
              ['body', 'body', 'string'],
              ['closedAt', 'closed_at', 'time.Time'],
              ['commentsCount', 'comments', 'int'],
              ['createdAt', 'created_at', 'time.Time'],
              ['id', 'node_id', 'string'], ['labels', 'labels', '[]Label'],
              ['isDraft', 'draft', '*bool'], ['isLocked', 'locked', 'bool'],
              ['number', 'number', 'int'],
              ['pullRequest', 'pull_request', 'PullRequest'],
              ['repositoryURL', 'repository_url', 'string'],
              ['stateInternal', 'state', 'string'],
              ['stateReason', 'state_reason', 'string'],
              ['title', 'title', 'string'], ['url', 'html_url', 'string'],
              ['updatedAt', 'updated_at', 'time.Time']],
    'Code': [['name', 'name', 'string'], ['path', 'path', 'string'],
             ['repository', 'repository', 'Repository'],
             ['sha', 'sha', 'string'],
             ['textMatches', 'text_matches', '[]TextMatch'],
             ['url', 'html_url', 'string']],
    'Commit': [['author', 'author', 'User'],
               ['committer', 'committer', 'User'], ['id', 'node_id', 'string'],
               ['info', 'commit', 'CommitInfo'],
               ['parents', 'parents', '[]Parent'],
               ['repo', 'repository', 'Repository'], ['sha', 'sha', 'string'],
               ['url', 'html_url', 'string']]
}

TEMPLATE_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|`[^`]*`|[^\s|]+|\|')
TEMPLATE_ACTION = re.compile(r'{{(-?)\s*(.*?)\s*(-?)}}', re.S)
TEMPLATE_DECLARATION = re.compile(r'(\$\w+)\s*(?:,\s*(\$\w+)\s*)?(:?=)\s*(.*)',
                                  re.S)
