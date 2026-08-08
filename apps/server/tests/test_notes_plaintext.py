from manabi_server.api.notes import derive_plain_text


def test_derive_plain_text_walks_nested_structure():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "Cache basics"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "A cache hit is "},
                    {"type": "text", "marks": [{"type": "bold"}], "text": "fast"},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "L1 is smallest"}],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    text = derive_plain_text(doc)
    assert "Cache basics" in text
    assert "A cache hit is fast" in text
    assert "L1 is smallest" in text


def test_derive_plain_text_empty_doc():
    assert derive_plain_text({"type": "doc", "content": [{"type": "paragraph"}]}) == ""
