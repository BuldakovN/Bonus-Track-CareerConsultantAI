import sys
from pathlib import Path

import uvicorn

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    uvicorn.run("model.llm_service:app", reload=False, loop="asyncio", port=8001, host="0.0.0.0")
