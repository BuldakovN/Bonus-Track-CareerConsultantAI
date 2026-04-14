#!/usr/bin/env python3
"""
Скрипт для запуска LLM API из папки model
"""
import uvicorn
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    print("🚀 Запуск LLM API...")
    print("📡 API будет доступен по адресу: http://localhost:8000")
    print("📋 Документация API: http://localhost:8000/docs")
    print("⏹️ Для остановки нажмите Ctrl+C")
    
    try:
        uvicorn.run(
            "itmo-hackathone.model.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
    except KeyboardInterrupt:
        print("\n⏹️ API остановлен")
    except Exception as e:
        print(f"❌ Ошибка при запуске API: {e}")
        sys.exit(1)

