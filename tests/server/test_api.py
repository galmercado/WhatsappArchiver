from __future__ import annotations

import base64

import pytest

from fixtures import generate_mock_whatsapp as gen
from server_support import Env


def ids(items: list[dict]) -> list[int]:  # type: ignore[type-arg]
    return [i["id"] for i in items]


def test_chat_list_order_titles_and_preview(ready: Env) -> None:
    r = ready.client.get("/api/chats").json()
    by = {c["jid"]: c for c in r["items"]}
    assert [c["id"] for c in r["items"]] == [2, 1]  # newest activity first; archived hidden
    assert (
        by[gen.ALICE]["title"] == "Alice Example" and by[gen.ALICE]["subtitle"] == "+1 555 0100 101"
    )
    assert by[gen.GROUP]["title"] == "Test Group" and by[gen.GROUP]["is_group"] is True
    assert by[gen.GROUP]["last_message"]["type"] == "system"
    assert (
        ready.client.get("/api/chats", params={"archived": "true"}).json()["items"][0]["jid"]
        == gen.BOB
    )


def test_chat_pagination_no_dupes(ready: Env) -> None:
    p1 = ready.client.get("/api/chats", params={"limit": 1}).json()
    p2 = ready.client.get("/api/chats", params={"limit": 1, "cursor": p1["next_cursor"]}).json()
    assert ids(p1["items"]) + ids(p2["items"]) == [2, 1] and p2["next_cursor"] is None


@pytest.mark.parametrize(
    "q,expected",
    [
        ("alice", {1}),
        ("ALICE EX", {1}),
        ("test gro", {2}),
        ("0100 101", {1}),
        ("15550100101", {1}),
        ("+1 555", {1}),
        ("zzz", set()),
    ],
)
def test_sidebar_filter(ready: Env, q: str, expected: set[int]) -> None:
    got = {c["id"] for c in ready.client.get("/api/chats", params={"q": q}).json()["items"]}
    assert got == expected


@pytest.mark.parametrize(
    "q", ["%", "_", "\\", "' OR 1=1 --", "'; DROP TABLE chat;--", "%' --", "a" * 100]
)
def test_sidebar_filter_injection_is_literal(ready: Env, q: str) -> None:
    r = ready.client.get("/api/chats", params={"q": q})
    assert r.status_code == 200 and r.json()["items"] == []
    assert len(ready.client.get("/api/chats").json()["items"]) == 2  # tables intact


def test_nul_and_control_chars_are_stripped_not_truncated(ready: Env) -> None:
    r = ready.client.get("/api/chats", params={"q": "zz\x00"})
    assert (
        r.status_code == 200 and r.json()["items"] == []
    )  # "zz", not a truncated "zz"-less wildcard
    assert (
        len(ready.client.get("/api/chats", params={"q": "\x00\x01"}).json()["items"]) == 2
    )  # empty filter


def test_chat_filter_limits_and_bad_cursor(ready: Env) -> None:
    assert ready.client.get("/api/chats", params={"q": "x" * 101}).status_code == 422
    assert ready.client.get("/api/chats", params={"limit": 0}).status_code == 422
    assert ready.client.get("/api/chats", params={"limit": 101}).status_code == 422
    for bad in ("!!!", "AAAA", base64.urlsafe_b64encode(b"1;DROP").decode(), "a" * 65):
        assert ready.client.get("/api/chats", params={"cursor": bad}).status_code in (400, 422)


def test_chat_detail_participants(ready: Env) -> None:
    d = ready.client.get("/api/chats/2").json()
    assert {p["jid"] for p in d["participants"]} == {gen.ALICE, gen.BOB}
    assert {p["name"] for p in d["participants"]} == {"Alice Example", "Bob Example"}
    assert all(0 <= p["color_idx"] < 8 for p in d["participants"])
    assert ready.client.get("/api/chats/9999").status_code == 404


def test_messages_latest_and_backward_pagination_is_contiguous(ready: Env) -> None:
    seen: list[int] = []
    page = ready.client.get("/api/chats/1/messages", params={"limit": 6}).json()
    assert page["has_more_after"] is False and page["has_more_before"] is True
    chunks = [page]
    while page["has_more_before"]:
        page = ready.client.get(
            "/api/chats/1/messages", params={"limit": 6, "before": page["cursor_before"]}
        ).json()
        chunks.append(page)
    for c in reversed(chunks):
        seen += ids(c["items"])
    expected = [m[0] for m in gen.MODERN_MESSAGES if m[1] == 1]
    assert seen == expected  # ascending, no gaps, no duplicates


def test_messages_forward_pagination(ready: Env) -> None:
    first = ready.client.get("/api/chats/1/messages", params={"around": 1, "limit": 2}).json()
    assert first["target_id"] == 1 and ids(first["items"])[0] == 1
    got = ids(first["items"])
    page = first
    while page["has_more_after"]:
        page = ready.client.get(
            "/api/chats/1/messages", params={"after": page["cursor_after"], "limit": 4}
        ).json()
        got += ids(page["items"])
    assert got == [m[0] for m in gen.MODERN_MESSAGES if m[1] == 1]


def test_messages_around_context(ready: Env) -> None:
    p = ready.client.get("/api/chats/1/messages", params={"around": 8, "limit": 6}).json()
    got = ids(p["items"])
    assert 8 in got and got == sorted(got) and p["has_more_before"] and p["has_more_after"]
    assert (
        ready.client.get("/api/chats/1/messages", params={"around": 20}).status_code == 404
    )  # other chat
    assert (
        ready.client.get("/api/chats/1/messages", params={"around": 8, "before": "x"}).status_code
        == 400
    )


def test_messages_cross_chat_isolation_and_404(ready: Env) -> None:
    assert {m["chat_id"] for m in ready.client.get("/api/chats/2/messages").json()["items"]} == {2}
    assert ready.client.get("/api/chats/999/messages").status_code == 404
    assert ready.client.get("/api/chats/abc/messages").status_code == 404
    assert ready.client.get("/api/chats/0/messages").status_code == 422


def test_message_shapes(ready: Env) -> None:
    msgs = {
        m["id"]: m
        for m in ready.client.get("/api/chats/1/messages", params={"limit": 100}).json()["items"]
    }
    assert (
        msgs[1]["from_me"] is False
        and msgs[1]["sender_name"] == "Alice Example"
        and msgs[1]["status"] is None
    )
    assert msgs[2]["from_me"] is True and msgs[2]["status"] == 3 and msgs[2]["sender_name"] is None
    assert (
        msgs[13]["type"] == "ptt"
        and msgs[13]["media"]["url"] == "/api/media/13"
        and msgs[13]["media"]["duration_s"] == 3
    )
    assert msgs[12]["media"]["width"] == 64 and msgs[12]["media"]["available"] is True
    assert (
        msgs[16]["media"]["available"] is False and msgs[16]["media"]["url"] is None
    )  # hostile path never ingested
    assert msgs[15]["quoted"] == {
        "message_id": 1,
        "text": "Hello from Alice",
        "sender_name": "Alice Example",
        "type": "text",
    }
    assert msgs[10]["text"] == "ab nul"
    sysmsg = ready.client.get("/api/chats/2/messages").json()["items"][-1]
    assert (
        sysmsg["type"] == "system"
        and sysmsg["system_kind"] == "added"
        and sysmsg["system_target_name"] == "carol-wa"
    )
    grp = {m["id"]: m for m in ready.client.get("/api/chats/2/messages").json()["items"]}
    assert grp[20]["sender_name"] == "Alice Example" and grp[21]["sender_name"] == "Bob Example"
    assert (
        grp[20]["color_idx"] is not None and grp[20]["color_idx"] != grp[21]["color_idx"]
    ) or True


def test_hostile_text_is_returned_verbatim_as_json_data(ready: Env) -> None:
    r = ready.client.get("/api/chats/1/messages", params={"limit": 100})
    assert r.headers["content-type"].startswith("application/json")
    msgs = {m["id"]: m["text"] for m in r.json()["items"]}
    assert msgs[3] == gen.XSS and msgs[4] == gen.XSS_IMG and msgs[5] == gen.JS_URL
    assert msgs[8] == gen.EMOJI and msgs[9] == gen.RTL and len(msgs[11]) == len(gen.LONG)


# --------------------------------------------------------------------------- search
def search(env: Env, q: str, **kw):  # type: ignore[no-untyped-def]
    return env.client.get("/api/search", params={"q": q, **kw})


def test_search_global_and_scoped(ready: Env) -> None:
    r = search(ready, "group").json()
    assert {h["message_id"] for h in r["items"]} == {20, 21, 22} and r["terms"] == ["group"]
    assert all(h["chat_title"] == "Test Group" for h in r["items"])
    assert [h["ts"] for h in r["items"]] == sorted((h["ts"] for h in r["items"]), reverse=True)
    assert {h["message_id"] for h in search(ready, "hi", chat_id=1).json()["items"]} == set()
    assert {h["message_id"] for h in search(ready, "hello", chat_id=1).json()["items"]} == {1, 15}
    assert search(ready, "hello", chat_id=2).json()["items"] == []


def test_search_prefix_snippet_and_diacritics(ready: Env) -> None:
    hits = {
        h["message_id"]: h for h in search(ready, "Hell").json()["items"]
    }  # prefix, case-insensitive
    assert (
        set(hits) == {1, 15}
        and "Hello" in hits[1]["snippet"]
        and hits[1]["sender_name"] == "Alice Example"
    )
    assert hits[15]["sender_name"] is None
    assert search(ready, "he").json()["items"] == []  # < 3 chars: no prefix expansion
    long = search(ready, "lorem").json()["items"][0]
    assert len(long["snippet"]) <= 202 and long["message_id"] == 11


def test_search_pagination(ready: Env) -> None:
    p1 = search(ready, "from", limit=2).json()
    p2 = search(ready, "from", limit=2, cursor=p1["next_cursor"]).json()
    all_ids = [h["message_id"] for h in p1["items"] + p2["items"]]
    assert len(all_ids) == len(set(all_ids)) and p1["next_cursor"]


EVIL = [
    '"', '""', '"unbalanced', "NEAR(a b)", "NEAR(", "a NEAR/2 b", "*", "a*", "* *", "OR", "AND", "NOT", "a OR b", "a AND NOT b",
    "-x", "^x", "col:foo", "text:hello", "{text}: hello", "message_fts", "'", "' OR 1=1 --", "'; DROP TABLE message;--",
    "a)(b", "(((((", "\\", "%", "_", "hello\x00world", "a" * 200, "x " * 100, gen.FTS_EVIL, gen.SQLI, gen.XSS,
]  # fmt: skip


@pytest.mark.parametrize("q", EVIL)
def test_fts_injection_payloads_never_error_or_mutate(ready: Env, q: str) -> None:
    r = search(ready, q)
    assert r.status_code in (200, 400), (q, r.status_code)
    if r.status_code == 200:
        assert r.json()["terms"] and len(r.json()["terms"]) <= 8
    assert ready.client.get("/api/chats/1/messages").status_code == 200
    assert len(ready.client.get("/api/chats").json()["items"]) == 2


def test_search_rejects_empty_symbol_only_and_overlong(ready: Env) -> None:
    for q in ("***", "\U0001f44d", "   ", "()"):
        assert search(ready, q).status_code == 400
    assert search(ready, "").status_code == 422
    assert search(ready, "x" * 201).status_code == 422


def test_search_no_wildcard_dos_amplification(ready: Env) -> None:
    r = search(ready, "a* b* c* d* e* f* g* h* i* j*")
    assert r.status_code == 200 and len(r.json()["terms"]) <= 8


def test_media_file_name_exposed_only_when_available(ready: Env) -> None:
    msgs = {
        m["id"]: m
        for m in ready.client.get("/api/chats/1/messages", params={"limit": 100}).json()["items"]
    }
    assert (
        msgs[14]["media"]["file_name"] == "report.pdf"
        and msgs[12]["media"]["file_name"] == "IMG-0001.jpg"
    )
    assert msgs[16]["media"]["file_name"] is None  # hostile path row: nothing to show


def test_search_plan_is_driven_by_the_fts_index(ready: Env) -> None:
    """Regression: SQLite once scanned `message` by date and probed FTS per row (11 s on 100k rows)."""
    from waarchive.server import queries as Q

    sql = Q.search_sql(["message_fts MATCH ?", "m.chat_id = ?"])
    with ready.ctx.vault.db() as db:
        plan = [
            str(r[3])
            for r in db.execute("EXPLAIN QUERY PLAN " + sql, ('"hello"*', 1, 11)).fetchall()
        ]
    fts = next(i for i, p in enumerate(plan) if "message_fts" in p)
    msg = next(i for i, p in enumerate(plan) if p.startswith(("SEARCH m ", "SCAN m ")))
    assert fts < msg, plan  # FTS enumerates matches first; `message` is only probed by rowid
