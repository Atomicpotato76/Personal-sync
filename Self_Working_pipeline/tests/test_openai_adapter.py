from services.adapters.openai_adapter import OpenAIJsonAdapter


def test_build_tools_disables_code_interpreter_by_default() -> None:
    adapter = OpenAIJsonAdapter(
        api_key="test-key",
        model="gpt-5.4",
        web_search_enabled=True,
        code_interpreter_enabled=False,
    )

    tools = adapter._build_tools()

    assert {"type": "web_search"} in tools
    assert all(tool.get("type") != "code_interpreter" for tool in tools)


def test_build_tools_adds_code_interpreter_with_container() -> None:
    adapter = OpenAIJsonAdapter(
        api_key="test-key",
        model="gpt-5.4",
        web_search_enabled=True,
        code_interpreter_enabled=True,
        code_interpreter_memory_limit="4g",
    )

    tools = adapter._build_tools()

    code_tools = [tool for tool in tools if tool.get("type") == "code_interpreter"]
    assert len(code_tools) == 1
    assert code_tools[0]["container"] == {"type": "auto", "memory_limit": "4g"}


def test_build_tools_preserves_pubmed_functions() -> None:
    adapter = OpenAIJsonAdapter(
        api_key="test-key",
        model="gpt-5.4",
        web_search_enabled=True,
        code_interpreter_enabled=False,
    )

    tools = adapter._build_tools()
    function_names = {tool.get("name") for tool in tools if tool.get("type") == "function"}

    assert function_names == {"search_pubmed", "fetch_abstract", "check_reference_genome"}
