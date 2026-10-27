from google.genai import types

from app.workflow.tools import compact_history

HTML = "<main>" + "x" * 20_000 + "</main>"


def _call(name, args):
    return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))])


def _resp(name, response):
    return types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name=name, response=response))])


def test_history_drops_written_html_and_old_reads():
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text="Design it")]),
        _call("write_screen", {"html": HTML, "note": "first"}),
        _resp("write_screen", {"ok": True, "version": 1}),
        _call("read_screen", {}),
        _resp("read_screen", {"ok": True, "html": HTML}),
        _call("edit_screen", {"old": "y" * 2000, "new": "short"}),
        _resp("edit_screen", {"ok": True, "version": 2}),
        _call("read_screen", {}),
        _resp("read_screen", {"ok": True, "html": HTML + "v2"}),
    ]
    out = compact_history(contents)
    assert out[0] is contents[0]
    write = out[1].parts[0].function_call.args
    assert write["note"] == "first" and write["html"].startswith("[20013 chars of HTML, saved")
    assert out[4].parts[0].function_response.response["html"].startswith("[superseded")
    edit = out[5].parts[0].function_call.args
    assert len(edit["old"]) < 200 and edit["new"] == "short"
    assert out[8].parts[0].function_response.response["html"].endswith("v2")  # latest read is kept
    total = sum(len(str(p.function_call.args if p.function_call else p.function_response.response if p.function_response else p.text))
                for c in out for p in c.parts)
    assert total < 25_000


def test_read_is_dropped_once_the_screen_changes():
    contents = [
        _call("read_screen", {}),
        _resp("read_screen", {"ok": True, "html": HTML}),
        _call("edit_screen", {"old": "x", "new": "y"}),
        _resp("edit_screen", {"ok": True, "version": 3}),
    ]
    out = compact_history(contents)
    assert out[1].parts[0].function_response.response["html"].startswith("[superseded")
