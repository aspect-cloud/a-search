from google.genai import types

duckduckgo_search_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name='duckduckgo_search',
            description='Use this tool to get information from the DuckDuckGo Instant Answer API. Ideal for quick, factual questions.',
            parameters={
                'type': 'OBJECT',
                'properties': {
                    'query': {
                        'type': 'STRING',
                        'description': 'A concise, factual search query. For example: "capital of France" or "height of Mount Everest".'
                    }
                },
                'required': ['query']
            }
        )
    ]
)

url_context_tool = types.Tool(
    url_context=types.UrlContext
)
