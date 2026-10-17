from corvo.agents.dir_summary.tools import count_words


async def test_count_words_returns_the_core_twin_s_count_as_a_tool_result() -> None:
    returned = await count_words.handler({"text": "one two  three\n"})

    assert returned == {"content": [{"type": "text", "text": "3"}]}


def test_count_words_takes_a_text_and_no_path() -> None:
    assert count_words.name == "count_words"
    assert count_words.input_schema == {"text": str}
