from google.genai import types

# For clarity, you can also import them directly, but referencing via types is common
# from google.genai.types import FunctionDeclaration, Tool

# Define the DuckDuckGo search tool that the model can use.
# This schema tells the model the tool's name, its purpose, and the parameters it accepts.
duckduckgo_search_tool = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name='duckduckgo_search',
            description='Use this tool to get information from the DuckDuckGo Instant Answer API. Ideal for quick, factual questions.',
            parameters={
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'A concise, factual search query. For example: "capital of France" or "height of Mount Everest".'
                    }
                },
                'required': ['query']
            }
        )
    ]
)

url_context_tool = types.Tool(
    url_context=types.UrlContext()
)
