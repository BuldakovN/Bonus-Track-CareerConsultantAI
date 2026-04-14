from datetime import datetime
from fastapi import FastAPI
from shema import Message, Context, LLMResponse, ProfessionRequest

from start_llm import Model
from prometheus_fastapi_instrumentator import Instrumentator

Model = Model()
app = FastAPI()
Instrumentator().instrument(app).expose(app)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Model API"}


@app.post("/start_talk/")
async def predict(context: Context) -> LLMResponse:
    try:
        print(f"🔍 API получил запрос от пользователя {context.user_id}: {context.prompt}")
        
        response = await Model.start_talk(user_input=context.prompt, user_id=context.user_id,
                                          parameters=context.parameters)

        # Получаем словарь профессий из метаданных пользователя, если они есть
        # И если пользователь находится в состоянии TALK (после получения рекомендаций)
        user_metadata = Model.user_metadata.get(context.user_id, {})
        user_state = Model.user_state.get(context.user_id, None)
        ai_recommendation_json = user_metadata.get('ai_recommendation_json')
        recommended_test = user_metadata.get('recommended_test')
        professions = None
        
        # Показываем профессии только если пользователь в состоянии TALK и есть рекомендации
        if (user_state == "talk" and ai_recommendation_json and 
            ai_recommendation_json.get('professions')):
            professions = ai_recommendation_json['professions']
            print(f"💼 Найдены профессии для пользователя в состоянии {user_state}: {list(professions.keys())}")
        elif user_state == "test" and recommended_test and Model.test_variant == 'v2':
            test_info = user_metadata['recommended_test']
            return LLMResponse(msg=response, professions=None, test_info=test_info)

        else:
            print(f"ℹ️ Профессии не показываем. Состояние: {user_state}, есть рекомендации: {bool(ai_recommendation_json)}")
        
        result = LLMResponse(msg=response, professions=professions, test_info=None)
        print(f"📤 Возвращаем результат с профессиями: {professions is not None}")
        return result
        
    except Exception as e:
        print(f"❌ Ошибка в API: {e}")
        import traceback
        traceback.print_exc()
        return LLMResponse(msg=f"Ошибка: {str(e)}", professions=None, test_info=None)

@app.post("/get_user_info/")
async def get_user_info(context: Context):
    response = Model.get_user_info(user_id=context.user_id)
    return Message(user_id=context.user_id, msg=str(response), timestamp=str(datetime.now()))


@app.post("/get_profession_info/")
async def get_profession_info(request: ProfessionRequest) -> LLMResponse:
    """Получает подробную информацию о профессии через RAG систему"""
    # Формируем запрос для получения подробной информации о профессии

    response = await Model.go_rag(profession_name=request.profession_name, user_id=request.user_id)

    user_metadata = Model.user_metadata.get(request.user_id, {})
    ai_recommendation_json = user_metadata.get('ai_recommendation_json')
    professions = None

    if ai_recommendation_json:
        professions = ai_recommendation_json['professions']

    return LLMResponse(msg=response, professions=professions)

@app.post("/get_profession_roadmap/")
async def get_profession_roadmap(request: ProfessionRequest) -> LLMResponse:
    """Получает подробную информацию о профессии через RAG систему"""
    # Формируем запрос для получения подробной информации о профессии

    response = await Model.go_rag_roadmap(profession_name=request.profession_name, user_id=request.user_id)

    user_metadata = Model.user_metadata.get(request.user_id, {})
    ai_recommendation_json = user_metadata.get('ai_recommendation_json')
    professions = None

    if ai_recommendation_json:
        professions = ai_recommendation_json['professions']

    return LLMResponse(msg=response, professions=professions)

@app.post("/clean_history/")
async def clean_history(context: Context):
    user_id = context.user_id
    await Model.clean_user_history(user_id=user_id)
    return LLMResponse(msg=f'История общения и все метаданные о пользователе {user_id} удалены')


