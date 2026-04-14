import uvicorn
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь для корректных импортов
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    # Запускаем из модуля model
    uvicorn.run("model.main:app", reload=False, loop='asyncio', port=8000, host="0.0.0.0")