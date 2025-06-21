import requests
import json

def get_instant_answer(query: str) -> dict:
    url = f"https://api.duckduckgo.com/?q={query}&format=json"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from DuckDuckGo: {e}")
        return {}
    except json.JSONDecodeError:
        print("Error decoding JSON from DuckDuckGo")
        return {}

def format_duckduckgo_html(ddg_result: dict) -> str:
    html = ""

    heading = ddg_result.get('Heading') or ddg_result.get('meta', {}).get('name')
    if heading:
        html += f'<b>{heading}</b><br>'

    abstract = ddg_result.get('AbstractText') or ddg_result.get('Abstract')
    if abstract:
        html += f'<i>{abstract}</i><br>'

    answer = ddg_result.get('Answer')
    if answer:
        html += f'<pre>{answer}</pre>'

    results = ddg_result.get('Results', [])
    if results:
        html += '<ul>'
        for r in results:
            title = r.get('Text')
            url = r.get('FirstURL')
            if title and url:
                html += f'<li><a href="{url}">{title}</a></li>'
        html += '</ul>'

    related = ddg_result.get('RelatedTopics', [])
    if related:
        html += '<b>Похожие темы:</b><ul>'
        for r in related:
            if isinstance(r, dict):
                title = r.get('Text')
                url = r.get('FirstURL')
                if title and url:
                    html += f'<li><a href="{url}">{title}</a></li>'
        html += '</ul>'

    src_url = ddg_result.get('meta', {}).get('src_url')
    if src_url:
        html += f'<br><i>Источник: <a href="{src_url}">{src_url}</a></i>'
    return html or '<i>Нет данных по вашему запросу.</i>'

if __name__ == '__main__':

    test_query = "What is the capital of France?"
    answer = get_instant_answer(test_query)
    if answer:
        print(json.dumps(answer, indent=2))
