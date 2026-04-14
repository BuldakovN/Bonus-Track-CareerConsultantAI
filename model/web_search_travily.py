from tavily import TavilyClient
import requests


class WebSearch:

    def __init__(self, api_key, api_base_url):
        self.api_base_url = api_base_url
        self.client = TavilyClient(api_key=api_key, api_base_url=api_base_url)
        self.check_health()

    async def search(self, query: str, max_results: int = 3):
        response = self.client.search(
            query=query,
            max_results=max_results,
            include_raw_content=True
        )

        return response['results']

    def check_health(self):
        try:
            response = requests.get(f'{self.api_base_url}/health', timeout=5)
            print(f"WebSearch health: {response.text}")
        except requests.RequestException as e:
            print(f"WebSearch Health check failed: {e}")

    async def create_course_info(self, query: str, max_results: int = 3):
        search_results = await self.search(query=query, max_results=max_results)
        formatted_courses = []

        for result in search_results:
            url = result.get('url', '')
            title = result.get('title', '')
            content = result.get('content', '')

            # Форматируем каждую запись
            course_info = f"url: {url}\nназвание курса: {title}\nописание курса: {content}\n"
            formatted_courses.append(course_info)

        return "\n".join(formatted_courses)
