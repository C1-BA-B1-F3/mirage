import pytest

from mirage.commands.cli.builtin.gh.template import render_template

ROWS = [{'title': 'a', 'number': 1}, {'title': 'b', 'number': 2}]


@pytest.mark.parametrize(
    "template,value,expected",
    [('{{range .}}{{if .ok}}{{.name}}{{else}}skip{{end}};{{end}}', [{
        'ok': True,
        'name': '雪'
    }, {
        'ok': False,
        'name': 'x'
    }], '雪;skip;'), ('{{range .}}x{{else}}empty{{end}}', [], 'empty'),
     ('{{pluck "name" . | join ", "}}', [{
         'name': 'one'
     }, {
         'name': 'two'
     }], 'one, two'),
     ('{{printf "%q %v %f" .name .ok .value}}', {
         'name': '雪',
         'ok': True,
         'value': 1.5
     }, '"雪" true 1.500000'),
     ('  {{- with .item -}}{{.name}}{{end}}  ', {
         'item': {
             'name': 'one'
         }
     }, 'one  '),
     ('{{range $i, $issue := .}}{{$i}}:{{$issue.title}};{{end}}',
      ROWS, '0:a;1:b;'),
     ('{{range $issue := .}}{{$issue.number}}{{end}}', ROWS, '12'),
     ('{{range $k, $v := index . 0}}{{$k}}={{$v}} {{end}}', ROWS,
      'number=1 title=a '),
     ('{{with $x := index . 0}}{{$x.title}}/{{.number}}{{end}}', ROWS, 'a/1'),
     ('{{if $t := len .}}{{$t}}{{else}}none{{end}}', ROWS, '2'),
     ('{{$n := len .}}{{range .}}{{.title}}{{$n}}{{end}}', ROWS, 'a2b2'),
     ('{{$n := 0}}{{range .}}{{$n = .number}}{{end}}{{$n}}', ROWS, '2')])
def test_templates(template, value, expected):
    assert render_template(template, value) == expected


def test_unclosed_blocks_are_errors():
    with pytest.raises(ValueError, match="unexpected EOF"):
        render_template("{{range .}}", [])


@pytest.mark.parametrize("template,message", [
    ("{{$nope}}", 'undefined variable "$nope"'),
    ("{{$nope = 1}}", 'undefined variable "$nope"'),
    ("{{if $a, $b := .}}x{{end}}", "too many declarations in if"),
])
def test_variable_errors(template, message):
    with pytest.raises(ValueError, match=message.replace("$", r"\$")):
        render_template(template, ROWS)
