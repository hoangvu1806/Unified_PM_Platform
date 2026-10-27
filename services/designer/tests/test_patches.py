from app.workflow.patches import apply_reply, extract_html

HTML = '<main class="p-6">\n  <h1 class="text-xl">Đăng nhập</h1>\n  <button class="bg-primary">Gửi</button>\n</main>'


def test_extract_html_drops_fences_and_prose():
    assert extract_html("Here it is:\n```html\n<div>Hi</div>\n```") == "<div>Hi</div>"
    assert extract_html("<section>x</section>\nDone.") == "<section>x</section>"


def test_extract_html_ignores_tags_mentioned_in_prose():
    reply = "I will fix the `<button>` labels and the `<aside>` drawer.\n```html\n<main><p>ok</p></main>\n```"
    assert extract_html(reply) == "<main><p>ok</p></main>"
    unfenced = "Fix `<td>` widths, then:\n<main>\n  <p>ok</p>\n</main>"
    assert extract_html(unfenced) == "<main>\n  <p>ok</p>\n</main>"


def test_ok_reply():
    edit = apply_reply(HTML, "OK")
    assert edit.ok and edit.html == HTML and not edit.applied


def test_search_replace_blocks_apply_exactly_and_with_loose_whitespace():
    reply = (
        "<<<<<<< SEARCH\n<h1 class=\"text-xl\">Đăng nhập</h1>\n=======\n<h1 class=\"text-3xl font-heading\">Đăng nhập</h1>\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\n<button   class=\"bg-primary\">Gửi</button>\n=======\n<button class=\"bg-primary h-12\">Gửi</button>\n>>>>>>> REPLACE"
    )
    edit = apply_reply(HTML, reply)
    assert edit.applied == 2 and not edit.failed
    assert 'text-3xl font-heading' in edit.html and 'h-12' in edit.html


def test_unknown_snippet_is_reported():
    edit = apply_reply(HTML, "<<<<<<< SEARCH\n<p>nope</p>\n=======\n<p>x</p>\n>>>>>>> REPLACE")
    assert edit.applied == 0 and edit.failed and edit.html == HTML


def test_full_rewrite_reply():
    new = "<main>" + "<p>đoạn văn</p>" * 30 + "</main>"
    edit = apply_reply(HTML, new)
    assert edit.rewrite and edit.html == new
